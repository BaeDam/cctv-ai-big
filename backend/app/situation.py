"""상황 판단 엔진.

프레임 단위 인식 결과(사람 박스·포즈·안전모·화재)를 시간 흐름으로 묶어서
"정말 위험한 상황인지"를 판단한다. 한 프레임만 보고 신고하면 앉기·눕기·물건 줍기 같은
동작에서 오탐이 많기 때문에, 사람(track_id)마다 상태 머신을 둔다.

    정상 ──(세로→가로 급변 + 무게중심 급하강)──▶ 쓰러짐 의심
    쓰러짐 의심 ──(confirm_sec 동안 누운 상태 유지)──▶ 쓰러짐 확정 (위험, 알림)
    쓰러짐 확정 ──(immobile_sec 동안 움직임 없음)──▶ 무반응 (긴급, 119)
    (어느 단계든 다시 일어서면 정상으로 복귀)

이 모듈은 OpenCV/YOLO에 의존하지 않는 순수 파이썬이라 단독으로 테스트할 수 있다.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"  # 주의
    DANGER = "danger"  # 위험
    CRITICAL = "critical"  # 긴급 → 신고 절차


class EventType(str, Enum):
    FALL = "fall"
    UNRESPONSIVE = "unresponsive"
    FIRE = "fire"
    SMOKE = "smoke"
    ZONE_INTRUSION = "zone_intrusion"
    NO_HELMET = "no_helmet"
    VIOLENCE = "violence"


# 긴급 이벤트별 신고 기관
EMERGENCY_TARGET = {
    EventType.UNRESPONSIVE: "119",
    EventType.FIRE: "119",
    EventType.SMOKE: "119",
    EventType.VIOLENCE: "112",
}

EVENT_LABEL = {
    EventType.FALL: "쓰러짐 감지",
    EventType.UNRESPONSIVE: "쓰러진 후 무반응 (중상 의심)",
    EventType.FIRE: "화재 감지",
    EventType.SMOKE: "연기 감지",
    EventType.ZONE_INTRUSION: "위험구역 진입",
    EventType.NO_HELMET: "안전모 미착용",
    EventType.VIOLENCE: "폭행/싸움 의심",
}

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2 (픽셀)
Point = tuple[float, float]


@dataclass
class Person:
    track_id: int
    bbox: BBox
    # COCO 포즈 키포인트 중 필요한 것만: left_shoulder, right_shoulder, left_hip, right_hip
    keypoints: dict[str, Point] | None = None
    has_helmet: bool | None = None  # None = 판단 불가(모델 없음, 머리 가려짐)


@dataclass
class FrameResult:
    camera_id: str
    timestamp: float  # 초 단위
    persons: list[Person] = field(default_factory=list)
    fire: bool = False
    smoke: bool = False


@dataclass
class Event:
    camera_id: str
    type: EventType
    severity: Severity
    message: str
    timestamp: float
    track_id: int | None = None
    bbox: BBox | None = None
    emergency: str | None = None  # "119" / "112" / None

    def to_dict(self) -> dict:
        return {
            "camera_id": self.camera_id,
            "type": self.type.value,
            "severity": self.severity.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "track_id": self.track_id,
            "bbox": list(self.bbox) if self.bbox else None,
            "emergency": self.emergency,
        }


@dataclass
class SituationConfig:
    upright_aspect: float = 0.8  # w/h 가 이보다 작으면 서 있음
    lying_aspect: float = 1.2  # w/h 가 이보다 크면 누워 있음
    torso_lying_deg: float = 60.0  # 몸통이 수직에서 이 각도 이상 기울면 누움
    fall_window_sec: float = 1.0  # 이 시간 안에 서 있다가 누우면 '쓰러짐'
    fall_drop_ratio: float = 0.25  # 무게중심 하강량 / 서 있을 때 키
    confirm_sec: float = 1.5  # 쓰러짐 의심 → 확정
    immobile_sec: float = 10.0  # 쓰러짐 확정 → 무반응(긴급)
    motion_ratio: float = 0.08  # 이동량 / 박스 대각선 이 값 미만이면 '움직임 없음'
    helmet_confirm_frames: int = 10
    fire_confirm_frames: int = 5
    track_ttl_sec: float = 5.0  # 이 시간 동안 안 보이면 추적 상태 삭제
    event_cooldown_sec: float = 60.0  # 같은 이벤트 반복 알림 간격


class _TrackState(str, Enum):
    NORMAL = "normal"
    FALL_SUSPECT = "fall_suspect"
    FALLEN = "fallen"
    UNRESPONSIVE = "unresponsive"


@dataclass
class _Track:
    history: deque  # (t, aspect, cy, height)
    state: _TrackState = _TrackState.NORMAL
    state_since: float = 0.0
    anchor: Point | None = None  # 쓰러진 뒤 움직임 기준점
    anchor_since: float = 0.0
    last_seen: float = 0.0
    no_helmet_frames: int = 0
    zones_inside: set = field(default_factory=set)


def _center(b: BBox) -> Point:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _size(b: BBox) -> tuple[float, float]:
    return (max(b[2] - b[0], 1e-6), max(b[3] - b[1], 1e-6))


def _torso_angle(kp: dict[str, Point] | None) -> float | None:
    """어깨 중점 → 엉덩이 중점 벡터가 수직선과 이루는 각도(도)."""
    if not kp:
        return None
    try:
        sx = (kp["left_shoulder"][0] + kp["right_shoulder"][0]) / 2
        sy = (kp["left_shoulder"][1] + kp["right_shoulder"][1]) / 2
        hx = (kp["left_hip"][0] + kp["right_hip"][0]) / 2
        hy = (kp["left_hip"][1] + kp["right_hip"][1]) / 2
    except KeyError:
        return None
    dx, dy = hx - sx, hy - sy
    if dx == 0 and dy == 0:
        return None
    return math.degrees(math.atan2(abs(dx), abs(dy)))


def point_in_polygon(p: Point, poly: list[Point]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


class SituationEngine:
    def __init__(
        self,
        config: SituationConfig | None = None,
        zones: dict[str, dict[str, list[Point]]] | None = None,
    ):
        """zones: {camera_id: {구역이름: [(x, y), ...]}}"""
        self.cfg = config or SituationConfig()
        self.zones = zones or {}
        self._tracks: dict[tuple[str, int], _Track] = {}
        self._fire_frames: dict[tuple[str, EventType], int] = {}
        self._last_emit: dict[tuple, float] = {}

    # ------------------------------------------------------------------ public
    def update(self, frame: FrameResult) -> list[Event]:
        events: list[Event] = []
        now = frame.timestamp
        for person in frame.persons:
            events += self._update_person(frame.camera_id, person, now)
        events += self._update_fire(frame, now)
        self._expire_tracks(now)
        return events

    def track_state(self, camera_id: str, track_id: int) -> str | None:
        t = self._tracks.get((camera_id, track_id))
        return t.state.value if t else None

    # ----------------------------------------------------------------- persons
    def _is_lying(self, person: Person) -> bool:
        w, h = _size(person.bbox)
        angle = _torso_angle(person.keypoints)
        if angle is not None:
            return angle >= self.cfg.torso_lying_deg
        return w / h >= self.cfg.lying_aspect

    def _update_person(self, cam: str, person: Person, now: float) -> list[Event]:
        cfg = self.cfg
        key = (cam, person.track_id)
        track = self._tracks.get(key)
        if track is None:
            track = _Track(history=deque(maxlen=120), state_since=now)
            self._tracks[key] = track
        track.last_seen = now

        w, h = _size(person.bbox)
        cx, cy = _center(person.bbox)
        aspect = w / h
        track.history.append((now, aspect, cy, h))
        lying = self._is_lying(person)
        events: list[Event] = []

        # 다시 일어서면 어느 단계든 정상으로 복귀
        if not lying and aspect < cfg.upright_aspect and track.state != _TrackState.NORMAL:
            track.state, track.state_since, track.anchor = _TrackState.NORMAL, now, None

        if track.state == _TrackState.NORMAL:
            if lying and self._fell_recently(track, now, cy):
                track.state, track.state_since = _TrackState.FALL_SUSPECT, now

        elif track.state == _TrackState.FALL_SUSPECT:
            if not lying:
                track.state, track.state_since = _TrackState.NORMAL, now
            elif now - track.state_since >= cfg.confirm_sec:
                track.state, track.state_since = _TrackState.FALLEN, now
                track.anchor, track.anchor_since = (cx, cy), now
                events.append(self._event(cam, EventType.FALL, Severity.DANGER, now, person))

        elif track.state == _TrackState.FALLEN:
            diag = math.hypot(w, h)
            ax, ay = track.anchor or (cx, cy)
            if math.hypot(cx - ax, cy - ay) / diag >= cfg.motion_ratio:
                # 움직임이 있으면 무반응 타이머 리셋
                track.anchor, track.anchor_since = (cx, cy), now
            elif now - track.anchor_since >= cfg.immobile_sec:
                track.state, track.state_since = _TrackState.UNRESPONSIVE, now
                events.append(
                    self._event(cam, EventType.UNRESPONSIVE, Severity.CRITICAL, now, person)
                )

        events += self._check_helmet(cam, person, track, now)
        events += self._check_zones(cam, person, track, now)
        return [e for e in events if e is not None]

    def _fell_recently(self, track: _Track, now: float, cy_now: float) -> bool:
        """fall_window_sec 안에 '서 있던' 기록이 있고, 그때보다 무게중심이 충분히 내려갔는가."""
        for t, aspect, cy, h in track.history:
            if now - t > self.cfg.fall_window_sec:
                continue
            if aspect < self.cfg.upright_aspect and (cy_now - cy) >= self.cfg.fall_drop_ratio * h:
                return True
        return False

    def _check_helmet(self, cam, person, track, now) -> list[Event]:
        if person.has_helmet is False:
            track.no_helmet_frames += 1
        elif person.has_helmet is True:
            track.no_helmet_frames = 0
        if track.no_helmet_frames == self.cfg.helmet_confirm_frames:
            return [self._event(cam, EventType.NO_HELMET, Severity.WARNING, now, person)]
        return []

    def _check_zones(self, cam, person, track, now) -> list[Event]:
        events = []
        foot = ((person.bbox[0] + person.bbox[2]) / 2, person.bbox[3])
        for name, poly in self.zones.get(cam, {}).items():
            inside = point_in_polygon(foot, poly)
            if inside and name not in track.zones_inside:
                track.zones_inside.add(name)
                events.append(
                    self._event(
                        cam, EventType.ZONE_INTRUSION, Severity.WARNING, now, person,
                        extra=f" ({name})", dedup=name,
                    )
                )
            elif not inside:
                track.zones_inside.discard(name)
        return events

    # -------------------------------------------------------------------- fire
    def _update_fire(self, frame: FrameResult, now: float) -> list[Event]:
        events = []
        for etype, seen in ((EventType.FIRE, frame.fire), (EventType.SMOKE, frame.smoke)):
            key = (frame.camera_id, etype)
            count = self._fire_frames.get(key, 0) + 1 if seen else 0
            self._fire_frames[key] = count
            if count == self.cfg.fire_confirm_frames:
                events.append(self._event(frame.camera_id, etype, Severity.CRITICAL, now))
        return [e for e in events if e is not None]

    # ----------------------------------------------------------------- helpers
    def _expire_tracks(self, now: float) -> None:
        for key in [k for k, t in self._tracks.items() if now - t.last_seen > self.cfg.track_ttl_sec]:
            del self._tracks[key]

    def _event(self, cam, etype, severity, now, person=None, extra="", dedup="") -> Event | None:
        track_id = person.track_id if person else None
        key = (cam, etype, track_id, dedup)
        last = self._last_emit.get(key)
        if last is not None and now - last < self.cfg.event_cooldown_sec:
            return None
        self._last_emit[key] = now
        return Event(
            camera_id=cam,
            type=etype,
            severity=severity,
            message=EVENT_LABEL[etype] + extra,
            timestamp=now,
            track_id=track_id,
            bbox=person.bbox if person else None,
            emergency=EMERGENCY_TARGET.get(etype) if severity == Severity.CRITICAL else None,
        )
