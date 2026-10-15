"""FastAPI 서버: 카메라 워커 실행, 이벤트 WebSocket 방송, 신고 사건 관리, 프론트엔드 제공.

실행:  cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
접속:  http://localhost:8000
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import GeminiAgent
from .dispatcher import EmergencyDispatcher, Incident, MockChannel, SmsChannel, WebhookChannel
from .situation import (
    EMERGENCY_TARGET,
    EVENT_LABEL,
    Event,
    EventType,
    FrameResult,
    SituationConfig,
    SituationEngine,
    Severity,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """backend/.env 의 KEY=VALUE 를 환경변수로 읽는다 (이미 설정된 값은 덮어쓰지 않음).
    API 키 같은 비밀 값은 이 파일에만 두고, 코드·설정 파일·git 에는 넣지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(BACKEND_DIR / ".env")
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
# CCTV_CONFIG 환경변수로 다른 설정 파일을 쓸 수 있다 (예: 테스트 영상용 설정)
CONFIG_PATH = Path(os.environ.get("CCTV_CONFIG", BACKEND_DIR / "config.yaml"))
CONFIG = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

CAMERAS = CONFIG.get("cameras", [])
CAMERA_NAMES = {c["id"]: c["name"] for c in CAMERAS}

_engine_lock = threading.Lock()
engine = SituationEngine(
    SituationConfig(**CONFIG.get("situation", {})),
    zones={
        cam: {name: [tuple(p) for p in poly] for name, poly in zs.items()}
        for cam, zs in (CONFIG.get("zones") or {}).items()
    },
)


def _build_channels(specs: list[dict]):
    channels = []
    for spec in specs:
        kind = spec.get("type")
        if kind == "mock":
            channels.append(MockChannel())
        elif kind == "webhook":
            channels.append(WebhookChannel(spec["url"]))
        elif kind == "sms":
            channels.append(SmsChannel(spec.get("recipients", [])))
    return channels or [MockChannel()]


class Hub:
    """워커 스레드 → asyncio 루프 → WebSocket 클라이언트들로 메시지 전달."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self.recent_events: list[dict] = []

    def publish(self, kind: str, data: dict) -> None:
        if kind == "event":
            self.recent_events = (self.recent_events + [data])[-200:]
        if self.loop and self.queue:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, {"kind": kind, "data": data})

    async def run(self) -> None:
        while True:
            msg = await self.queue.get()
            for ws in list(self.clients):
                try:
                    await ws.send_json(msg)
                except Exception:
                    self.clients.discard(ws)


hub = Hub()
emergency_cfg = CONFIG.get("emergency", {})
dispatcher = EmergencyDispatcher(
    channels=_build_channels(emergency_cfg.get("channels", [])),
    countdown_sec=float(emergency_cfg.get("countdown_sec", 15)),
    site_name=CONFIG.get("site", {}).get("name", ""),
    site_address=CONFIG.get("site", {}).get("address", ""),
    camera_names=CAMERA_NAMES,
    on_change=lambda inc: hub.publish("incident", inc.to_dict()),
)
_dispatch_lock = threading.Lock()


agent_cfg = CONFIG.get("agent", {}) or {}
agent = GeminiAgent(model=agent_cfg.get("model", "gemini-flash-latest"), timeout=float(agent_cfg.get("timeout_sec", 15)))
AGENT_ON = agent.enabled and agent_cfg.get("enabled", True)
log.info("AI 에이전트(Gemini): %s", f"사용 ({agent.model})" if AGENT_ON else "사용 안 함 (GEMINI_API_KEY 없음)")


def handle_events(events: list[Event]) -> None:
    for ev in events:
        hub.publish("event", ev.to_dict())
        if not ev.emergency:
            continue
        with _dispatch_lock:
            before = set(dispatcher.incidents)
            inc = dispatcher.escalate(ev)
            is_new = inc is not None and inc.id not in before
        if is_new and AGENT_ON:
            _ask_agent(inc)


def _ask_agent(inc: Incident) -> None:
    """신고 창은 즉시 띄우고, AI 판단은 뒤에서 받아와 창에 덧붙인다 (감지 속도에 영향 없음)."""
    worker = workers.get(inc.event.camera_id)
    snapshot = worker.latest_jpeg if worker else None
    if snapshot is None:
        dispatcher.attach_ai(inc.id, {"error": "장면 사진 없음 (시뮬레이션 이벤트)"})
        return
    dispatcher.attach_ai(inc.id, {"pending": True})

    def run():
        result = agent.assess([snapshot], CAMERA_NAMES.get(inc.event.camera_id, inc.event.camera_id), inc.event.message)
        with _dispatch_lock:
            dispatcher.attach_ai(inc.id, result)

    threading.Thread(target=run, daemon=True, name=f"agent-{inc.id}").start()


def on_frame(result: FrameResult) -> list[Event]:
    with _engine_lock:
        events = engine.update(result)
    handle_events(events)
    return events


def fallen_boxes(camera_id: str):
    with _engine_lock:
        return engine.fallen_boxes(camera_id)


workers: dict = {}


def _split_cpu_threads(n_cameras: int) -> None:
    """CPU로 분석할 때 카메라들이 모든 코어를 서로 차지하려고 다투면 오히려 느려진다.
    코어를 카메라 수로 나눠 각자 쓰게 한다 (GPU 사용 시에는 영향 거의 없음)."""
    import torch

    threads = max(1, (os.cpu_count() or 1) // max(1, n_cameras))
    torch.set_num_threads(threads)
    log.info("CPU 스레드: 카메라당 %d개 (카메라 %d대)", threads, n_cameras)


def start_workers() -> None:
    sources = [c for c in CAMERAS if c.get("source")]
    if not sources:
        log.info("영상 소스가 설정된 카메라가 없음 → 화면은 데모 영상으로 표시")
        return
    try:
        from .detector import Detector
        from .stream import CameraWorker
    except ImportError as exc:
        log.error("AI 의존성(ultralytics/opencv) 없음, 분석 비활성화: %s", exc)
        return
    models = CONFIG.get("models", {})
    _split_cpu_threads(len(sources))

    def factory():
        return Detector(
            models.get("pose", "yolo11n-pose.pt"),
            models.get("helmet"),
            models.get("fire"),
            device=str(models.get("device", "auto")),
            imgsz=int(models.get("imgsz", 640)),
            conf=float(models.get("conf", 0.25)),
        )

    for cam in sources:
        w = CameraWorker(
            cam["id"],
            cam["source"],
            factory,
            on_frame,
            fallen_boxes=fallen_boxes,
            fps=float(models.get("fps", 0)),
            display_fps=float(models.get("display_fps", 15)),
        )
        w.start()
        workers[cam["id"]] = w


async def tick_dispatcher() -> None:
    while True:
        with _dispatch_lock:
            dispatcher.tick()
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.loop = asyncio.get_running_loop()
    hub.queue = asyncio.Queue()
    tasks = [asyncio.create_task(hub.run()), asyncio.create_task(tick_dispatcher())]
    start_workers()
    yield
    for w in workers.values():
        w.stop()
    for t in tasks:
        t.cancel()


app = FastAPI(title="CCTV AI Agent", lifespan=lifespan)


@app.get("/api/config")
def get_config():
    return {
        "site": CONFIG.get("site", {}),
        "countdown_sec": dispatcher.countdown_sec,
        "agent": {"enabled": bool(AGENT_ON), "model": agent.model if AGENT_ON else None},
        "cameras": [
            {"id": c["id"], "name": c["name"], "stream": f"/stream/{c['id']}.mjpg" if c["id"] in workers else None}
            for c in CAMERAS
        ],
    }


@app.get("/api/stats")
def get_stats():
    """카메라별 AI 분석 속도 (추론 시간 ms, 초당 분석 프레임)."""
    return [w.stats() for w in workers.values()]


@app.get("/api/events")
def get_events():
    return hub.recent_events


@app.delete("/api/events")
def clear_events():
    """AI 이벤트 목록 비우기 (신고 사건 기록은 유지)."""
    hub.recent_events = []
    hub.publish("events_cleared", {})
    return {"ok": True}


@app.get("/api/incidents")
def get_incidents():
    return [inc.to_dict() for inc in dispatcher.incidents.values()]


def _incident_or_404(inc: Incident | None) -> dict:
    if inc is None:
        raise HTTPException(404, "사건 없음")
    return inc.to_dict()


@app.post("/api/incidents/{incident_id}/cancel")
def cancel_incident(incident_id: int):
    with _dispatch_lock:
        return _incident_or_404(dispatcher.cancel(incident_id))


@app.post("/api/incidents/{incident_id}/confirm")
def confirm_incident(incident_id: int):
    with _dispatch_lock:
        return _incident_or_404(dispatcher.confirm(incident_id))


class SimulateRequest(BaseModel):
    camera_id: str
    type: EventType


_SIM_SEVERITY = {
    EventType.FALL: Severity.DANGER,
    EventType.ZONE_INTRUSION: Severity.WARNING,
    EventType.NO_HELMET: Severity.WARNING,
}


@app.post("/api/simulate")
def simulate(req: SimulateRequest):
    """시연용: 실제 영상 없이 이벤트를 발생시켜 전체 흐름(알림→카운트다운→신고)을 확인."""
    severity = _SIM_SEVERITY.get(req.type, Severity.CRITICAL)
    ev = Event(
        camera_id=req.camera_id,
        type=req.type,
        severity=severity,
        message=EVENT_LABEL[req.type] + " (시뮬레이션)",
        timestamp=time.time(),
        emergency=EMERGENCY_TARGET.get(req.type) if severity == Severity.CRITICAL or req.type == EventType.FALL else None,
    )
    handle_events([ev])
    return ev.to_dict()


@app.get("/stream/{camera_id}.mjpg")
async def mjpeg(camera_id: str):
    worker = workers.get(camera_id)
    if worker is None:
        raise HTTPException(404, "분석 중인 카메라 아님")

    async def gen():
        last = None
        while True:
            frame = worker.latest_jpeg
            if frame is not None and frame is not last:
                last = frame
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # 클라이언트 메시지는 사용 안 함 (연결 유지용)
    except WebSocketDisconnect:
        hub.clients.discard(ws)


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
