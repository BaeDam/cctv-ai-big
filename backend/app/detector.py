"""YOLO 기반 프레임 인식 → FrameResult 변환.

- 사람 + 포즈 + 추적: Ultralytics pose 모델 (`yolo11n-pose.pt`, 첫 실행 시 자동 다운로드)
- 안전모: 안전모 데이터셋으로 학습한 커스텀 모델 (클래스 예: helmet / head)
- 화재·연기: 화재 데이터셋(D-Fire 등)으로 학습한 커스텀 모델 (클래스 예: fire / smoke)
커스텀 모델 경로를 비워두면 해당 항목은 판단하지 않는다.

카메라마다 추적 상태가 따로 있어야 하므로 Detector 는 카메라당 하나씩 만든다.
"""

from __future__ import annotations

from .situation import FrameResult, Person

# COCO 키포인트 인덱스
_KP = {"left_shoulder": 5, "right_shoulder": 6, "left_hip": 11, "right_hip": 12}


class Detector:
    def __init__(
        self,
        pose_model: str = "yolo11n-pose.pt",
        helmet_model: str | None = None,
        fire_model: str | None = None,
        conf: float = 0.4,
        kp_conf: float = 0.5,
    ):
        from ultralytics import YOLO  # 무거운 의존성이라 실제 사용할 때만 import

        self.pose = YOLO(pose_model)
        self.helmet = YOLO(helmet_model) if helmet_model else None
        self.fire = YOLO(fire_model) if fire_model else None
        self.conf = conf
        self.kp_conf = kp_conf

    def detect(self, frame, camera_id: str, ts: float) -> FrameResult:
        result = FrameResult(camera_id=camera_id, timestamp=ts)

        r = self.pose.track(
            frame, persist=True, classes=[0], conf=self.conf, tracker="bytetrack.yaml", verbose=False
        )[0]
        if r.boxes is not None and r.boxes.id is not None:
            boxes = r.boxes.xyxy.cpu().numpy()
            ids = r.boxes.id.int().cpu().tolist()
            kxy = r.keypoints.xy.cpu().numpy() if r.keypoints is not None else None
            kcf = (
                r.keypoints.conf.cpu().numpy()
                if r.keypoints is not None and r.keypoints.conf is not None
                else None
            )
            for i, (box, tid) in enumerate(zip(boxes, ids)):
                kp = None
                if kxy is not None and kcf is not None:
                    if all(kcf[i][j] >= self.kp_conf for j in _KP.values()):
                        kp = {name: (float(kxy[i][j][0]), float(kxy[i][j][1])) for name, j in _KP.items()}
                result.persons.append(Person(track_id=tid, bbox=tuple(map(float, box)), keypoints=kp))

        if self.helmet is not None and result.persons:
            self._apply_helmet(frame, result.persons)

        if self.fire is not None:
            fr = self.fire(frame, conf=self.conf, verbose=False)[0]
            names = {int(c): fr.names[int(c)].lower() for c in fr.boxes.cls.tolist()}
            labels = set(names.values())
            result.fire = "fire" in labels
            result.smoke = "smoke" in labels
        return result

    def _apply_helmet(self, frame, persons: list[Person]) -> None:
        hr = self.helmet(frame, conf=self.conf, verbose=False)[0]
        dets = [
            (hr.names[int(c)].lower(), b)
            for c, b in zip(hr.boxes.cls.tolist(), hr.boxes.xyxy.cpu().numpy().tolist())
        ]
        for p in persons:
            x1, y1, x2, y2 = p.bbox
            head_bottom = y1 + (y2 - y1) * 0.3  # 사람 박스 위쪽 30% 를 머리 영역으로 본다
            for label, (bx1, by1, bx2, by2) in dets:
                cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
                if not (x1 <= cx <= x2 and y1 - (y2 - y1) * 0.1 <= cy <= head_bottom):
                    continue
                if "helmet" in label or "hardhat" in label:
                    p.has_helmet = True
                    break
                if label in ("head", "no_helmet", "no-helmet"):
                    p.has_helmet = False
