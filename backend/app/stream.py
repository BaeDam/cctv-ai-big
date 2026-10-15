"""카메라 1대 = 스레드 2개 (영상 수신 / AI 분석).

빠른 감지를 위한 구조:
  - 수신 스레드: 카메라에서 프레임을 쉬지 않고 읽고 '가장 최신 프레임 1장'만 보관한다.
    RTSP 는 읽기가 밀리면 버퍼에 옛날 장면이 쌓여 몇 초씩 늦어지는데, 이를 막는다.
  - 분석 스레드: 분석이 끝나자마자 그 순간의 최신 프레임을 가져가 분석한다 (밀린 프레임은 버림).
    fps=0 이면 하드웨어가 허용하는 최대 속도로 분석한다.
  - 화면용 영상은 분석 속도와 상관없이 display_fps 로 부드럽게 내보내고,
    가장 최근 분석 결과(박스)를 겹쳐 그린다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

from .detector import Detector
from .situation import FrameResult, Severity

log = logging.getLogger("stream")

_SEVERITY_COLOR = {  # BGR
    Severity.WARNING: (0, 210, 255),
    Severity.DANGER: (0, 140, 255),
    Severity.CRITICAL: (0, 0, 255),
}


class CameraWorker:
    def __init__(
        self,
        camera_id: str,
        source: str,
        detector_factory: Callable[[], Detector],
        on_frame: Callable[[FrameResult], list],
        fallen_boxes: Callable[[str], list] | None = None,
        fps: float = 0,
        display_fps: float = 15,
        loop_file: bool = True,
    ):
        self.camera_id = camera_id
        self.source = int(source) if str(source).isdigit() else source
        self.is_file = isinstance(self.source, str) and not self.source.startswith(("rtsp://", "http://", "https://"))
        self.detector_factory = detector_factory
        self.on_frame = on_frame
        self.fallen_boxes = fallen_boxes
        self.min_interval = 1.0 / fps if fps > 0 else 0.0
        self.display_interval = 1.0 / display_fps
        self.loop_file = loop_file

        self.latest_jpeg: bytes | None = None
        self._frame = None  # 가장 최신 원본 프레임
        self._frame_seq = 0
        self._frame_cond = threading.Condition()
        self._result: FrameResult | None = None
        self._marks: dict[int, tuple[float, Severity]] = {}  # track_id → (표시 종료 시각, 위험도)
        self._infer_ms: deque = deque(maxlen=30)
        self._infer_times: deque = deque(maxlen=30)
        self._stop = threading.Event()
        self.ready = threading.Event()
        self._threads = [
            threading.Thread(target=self._grab_loop, daemon=True, name=f"grab-{camera_id}"),
            threading.Thread(target=self._infer_loop, daemon=True, name=f"ai-{camera_id}"),
        ]

    # ---------------------------------------------------------------- 제어
    def start(self) -> None:
        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop.set()
        with self._frame_cond:
            self._frame_cond.notify_all()

    def stats(self) -> dict:
        now = time.time()
        recent = [t for t in self._infer_times if now - t < 3]
        fps = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 1 and recent[-1] > recent[0] else 0.0
        ms = sum(self._infer_ms) / len(self._infer_ms) if self._infer_ms else None
        return {
            "camera_id": self.camera_id,
            "ready": self.ready.is_set(),
            "infer_ms": round(ms, 1) if ms is not None else None,
            "analysis_fps": round(fps, 1),
            "persons": len(self._result.persons) if self._result else 0,
        }

    # ------------------------------------------------------------ 영상 수신
    def _grab_loop(self) -> None:
        import cv2

        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                log.error("[%s] 영상 열기 실패, 3초 후 재시도: %s", self.camera_id, self.source)
                time.sleep(3)
                continue
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 카메라 쪽 버퍼 최소화 (지원하는 경우)
            # 영상 파일은 실제 카메라처럼 원래 속도로 재생한다
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 0
            frame_gap = 1.0 / src_fps if self.is_file and 1 <= src_fps <= 120 else 0.0
            next_t = time.time()
            last_display = 0.0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                with self._frame_cond:
                    self._frame = frame
                    self._frame_seq += 1
                    self._frame_cond.notify_all()
                now = time.time()
                if now - last_display >= self.display_interval:
                    last_display = now
                    self._encode(cv2, frame, now)
                if frame_gap:
                    next_t += frame_gap
                    delay = next_t - time.time()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        next_t = time.time()
            cap.release()
            if self.is_file and not self.loop_file:
                break

    # ------------------------------------------------------------- AI 분석
    def _infer_loop(self) -> None:
        detector = self.detector_factory()
        log.info("[%s] AI 모델 준비 완료 (device=%s)", self.camera_id, getattr(detector, "device", "?"))
        self.ready.set()
        seen = 0
        while not self._stop.is_set():
            with self._frame_cond:
                while self._frame_seq == seen and not self._stop.is_set():
                    self._frame_cond.wait(timeout=1.0)
                if self._stop.is_set():
                    break
                frame, seen = self._frame, self._frame_seq
            t0 = time.time()
            result = detector.detect(frame, self.camera_id, t0)
            t1 = time.time()
            self._infer_ms.append((t1 - t0) * 1000)
            self._infer_times.append(t1)
            self._result = result
            for ev in self.on_frame(result):
                if ev.track_id is not None:
                    self._marks[ev.track_id] = (t1 + 15, ev.severity)
            if self.min_interval:
                rest = self.min_interval - (time.time() - t0)
                if rest > 0:
                    time.sleep(rest)

    # ------------------------------------------------------------ 화면 출력
    def _encode(self, cv2, frame, now: float) -> None:
        frame = frame.copy()
        result = self._result
        if result is not None:
            for p in result.persons:
                x1, y1, x2, y2 = map(int, p.bbox)
                color = (80, 220, 80)
                mark = self._marks.get(p.track_id)
                if mark and mark[0] > now:
                    color = _SEVERITY_COLOR.get(mark[1], color)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                label = f"#{p.track_id}" + (" no-helmet" if p.has_helmet is False else "")
                cv2.putText(frame, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                if p.keypoints:
                    for x, y in p.keypoints.values():
                        cv2.circle(frame, (int(x), int(y)), 3, color, -1)
            # 쓰러진 사람은 AI 인식이 끊기는 경우가 많아 마지막으로 확인된 위치를 표시한다
            for (x1, y1, x2, y2), state, visible in (self.fallen_boxes(self.camera_id) if self.fallen_boxes else []):
                if visible:
                    continue  # 인식 중이면 위에서 이미 그림
                color = (0, 0, 255) if state == "unresponsive" else (0, 140, 255)
                p1, p2 = (int(x1), int(y1)), (int(x2), int(y2))
                cv2.rectangle(frame, p1, p2, color, 2, lineType=cv2.LINE_AA)
                label = "NO MOTION" if state == "unresponsive" else "FALL?"
                cv2.putText(frame, label, (p1[0], max(p1[1] - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            if result.fire or result.smoke:
                cv2.putText(frame, "FIRE/SMOKE", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
        s = self.stats()
        if s["infer_ms"] is not None:
            text = f"AI {s['infer_ms']:.0f}ms  {s['analysis_fps']:.1f}fps"
            cv2.putText(frame, text, (8, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            self.latest_jpeg = buf.tobytes()
