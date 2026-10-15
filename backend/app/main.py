"""FastAPI 서버: 카메라 워커 실행, 이벤트 WebSocket 방송, 신고 사건 관리, 프론트엔드 제공.

실행:  cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
접속:  http://localhost:8000
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
CONFIG = yaml.safe_load((BACKEND_DIR / "config.yaml").read_text(encoding="utf-8"))

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


def handle_events(events: list[Event]) -> None:
    for ev in events:
        hub.publish("event", ev.to_dict())
        if ev.severity == Severity.CRITICAL:
            with _dispatch_lock:
                dispatcher.escalate(ev)


def on_frame(result: FrameResult) -> list[Event]:
    with _engine_lock:
        events = engine.update(result)
    handle_events(events)
    return events


workers: dict = {}


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

    def factory():
        return Detector(
            models.get("pose", "yolo11n-pose.pt"),
            models.get("helmet"),
            models.get("fire"),
            device=str(models.get("device", "auto")),
        )

    for cam in sources:
        w = CameraWorker(cam["id"], cam["source"], factory, on_frame, fps=float(models.get("fps", 5)))
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
        "cameras": [
            {"id": c["id"], "name": c["name"], "stream": f"/stream/{c['id']}.mjpg" if c["id"] in workers else None}
            for c in CAMERAS
        ],
    }


@app.get("/api/events")
def get_events():
    return hub.recent_events


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
        emergency=EMERGENCY_TARGET.get(req.type) if severity == Severity.CRITICAL else None,
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
