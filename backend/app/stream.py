"""카메라 1대 = 워커 스레드 1개.

RTSP/영상 파일에서 프레임을 읽고 → 인식 → 상황 판단 → 결과 콜백.
브라우저에 보여줄 박스가 그려진 최신 JPEG 프레임도 보관한다 (MJPEG 스트림용).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .detector import Detector
from .situation import FrameResult, Severity

log = logging.getLogger("stream")

_SEVERITY_COLOR = {  # BGR
    Severity.WARNING: (0, 210, 255),
    Severity.DANGER: (0, 140, 255),
    Severity.CRITICAL: (0, 0, 255),
}


class CameraWorker(threading.Thread):
    def __init__(
        self,
        camera_id: str,
        source: str,
        detector_factory: Callable[[], Detector],
        on_frame: Callable[[FrameResult], list],
        fps: float = 5.0,
    ):
        super().__init__(daemon=True, name=f"cam-{camera_id}")
        self.camera_id = camera_id
        self.source = int(source) if str(source).isdigit() else source
        self.detector_factory = detector_factory
        self.on_frame = on_frame
        self.interval = 1.0 / fps
        self.latest_jpeg: bytes | None = None
        self._stop = threading.Event()
        self._danger_until: dict[int, tuple[float, Severity]] = {}

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        import cv2

        detector = self.detector_factory()
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.source)
            if not cap.isOpened():
                log.error("[%s] 영상 열기 실패, 5초 후 재시도: %s", self.camera_id, self.source)
                time.sleep(5)
                continue
            last = 0.0
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    # 영상 파일이면 처음부터 반복, RTSP 면 재연결
                    break
                now = time.time()
                if now - last < self.interval:
                    continue
                last = now
                result = detector.detect(frame, self.camera_id, now)
                events = self.on_frame(result)
                for ev in events:
                    if ev.track_id is not None:
                        self._danger_until[ev.track_id] = (now + 10, ev.severity)
                self._draw(cv2, frame, result, now)
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    self.latest_jpeg = buf.tobytes()
            cap.release()

    def _draw(self, cv2, frame, result: FrameResult, now: float) -> None:
        for p in result.persons:
            x1, y1, x2, y2 = map(int, p.bbox)
            color = (80, 220, 80)
            mark = self._danger_until.get(p.track_id)
            if mark and mark[0] > now:
                color = _SEVERITY_COLOR.get(mark[1], color)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label = f"#{p.track_id}" + (" no-helmet" if p.has_helmet is False else "")
            cv2.putText(frame, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        if result.fire or result.smoke:
            cv2.putText(frame, "FIRE/SMOKE", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
