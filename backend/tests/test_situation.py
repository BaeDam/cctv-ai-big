from app.situation import EventType, FrameResult, Person, Severity, SituationConfig, SituationEngine

CAM = "cam01"
STANDING = (100, 100, 160, 280)  # w=60, h=180 → 세로
LYING = (60, 230, 240, 290)  # w=180, h=60 → 가로, 무게중심 크게 하강


def frame(t, *persons, fire=False):
    return FrameResult(camera_id=CAM, timestamp=t, persons=list(persons), fire=fire)


def run(engine, seq):
    events = []
    for t, bbox in seq:
        events += engine.update(frame(t, Person(1, bbox)))
    return events


def types(events):
    return [e.type for e in events]


def test_fall_then_unresponsive_escalates_to_119():
    eng = SituationEngine(SituationConfig(confirm_sec=1.5, immobile_sec=10))
    seq = [(t * 0.2, STANDING) for t in range(5)]  # 0.0~0.8초 서 있음
    seq += [(1.0 + t * 0.2, LYING) for t in range(80)]  # 1.0초부터 쓰러져 움직임 없음
    events = run(eng, seq)

    assert types(events) == [EventType.FALL, EventType.UNRESPONSIVE]
    fall, unresp = events
    assert fall.severity == Severity.DANGER and fall.emergency is None
    assert unresp.severity == Severity.CRITICAL and unresp.emergency == "119"
    assert 2.4 <= fall.timestamp <= 2.8
    assert unresp.timestamp >= fall.timestamp + 10


def test_lying_down_slowly_is_not_a_sudden_fall():
    eng = SituationEngine(SituationConfig(lying_confirm_sec=3.0))
    seq = [(t * 0.2, STANDING) for t in range(5)]
    # 바닥에 천천히 앉았다가 3초 뒤 눕기 → 1초 안에 '서 있음→누움' 급변이 없으므로 즉시 판정하지 않음
    seq += [(1.0 + t * 0.2, (95, 200, 175, 290)) for t in range(15)]  # 바닥에 앉음(w/h≈0.89)
    seq += [(4.0 + t * 0.2, LYING) for t in range(10)]  # 2초간 누움
    assert run(eng, seq) == []


def test_lying_long_without_seen_fall_is_detected():
    # 넘어지는 순간을 놓쳐도(새 추적 ID로 처음부터 누운 채 등장) 누운 상태가 지속되면 쓰러짐
    eng = SituationEngine(SituationConfig(lying_confirm_sec=3.0))
    events = run(eng, [(t * 0.2, LYING) for t in range(20)])
    assert types(events) == [EventType.FALL]
    assert "지속" in events[0].message
    assert 3.0 <= events[0].timestamp <= 3.2


def test_getting_up_cancels_fall():
    eng = SituationEngine(SituationConfig(confirm_sec=1.5))
    seq = [(t * 0.2, STANDING) for t in range(5)]
    seq += [(1.0, LYING), (1.2, LYING), (1.4, STANDING), (1.6, STANDING)]  # 넘어졌다 바로 일어남
    seq += [(1.8 + t * 0.2, STANDING) for t in range(20)]
    assert run(eng, seq) == []
    assert eng.track_state(CAM, 1) == "normal"


def test_moving_after_fall_resets_unresponsive_timer():
    eng = SituationEngine(SituationConfig(confirm_sec=1.0, immobile_sec=5))
    seq = [(t * 0.2, STANDING) for t in range(5)]
    seq += [(1.0 + t * 0.2, LYING) for t in range(20)]  # 1.0~4.8초 누워 있음 (확정 ≈2.0초)
    # 4초째부터 몸을 움직임 (좌우로 굴러감)
    for i in range(20):
        dx = 30 if i % 2 else 0
        seq.append((5.0 + i * 0.2, (LYING[0] + dx, LYING[1], LYING[2] + dx, LYING[3])))
    events = run(eng, seq)
    assert types(events) == [EventType.FALL]


def test_fire_requires_consecutive_frames():
    eng = SituationEngine(SituationConfig(fire_confirm_frames=5))
    events = []
    for i in range(4):
        events += eng.update(frame(i * 0.2, fire=True))
    events += eng.update(frame(1.0, fire=False))  # 끊김 → 카운트 리셋
    assert events == []
    for i in range(5):
        events += eng.update(frame(2 + i * 0.2, fire=True))
    assert types(events) == [EventType.FIRE]
    assert events[0].emergency == "119"


def test_zone_intrusion_once_per_entry():
    zones = {CAM: {"크레인": [(0, 300), (400, 300), (400, 500), (0, 500)]}}
    eng = SituationEngine(SituationConfig(event_cooldown_sec=0), zones=zones)
    outside = (100, 100, 160, 280)  # 발 y=280 → 구역 밖
    inside = (100, 150, 160, 330)  # 발 y=330 → 구역 안
    seq = [(0, outside), (0.2, inside), (0.4, inside), (0.6, outside), (0.8, inside)]
    events = run(eng, seq)
    assert types(events) == [EventType.ZONE_INTRUSION, EventType.ZONE_INTRUSION]
    assert "크레인" in events[0].message


def test_no_helmet_after_consecutive_frames():
    eng = SituationEngine(SituationConfig(helmet_confirm_frames=3))
    events = []
    for i in range(5):
        events += eng.update(frame(i * 0.2, Person(7, STANDING, has_helmet=False)))
    assert types(events) == [EventType.NO_HELMET]
    assert events[0].severity == Severity.WARNING


def test_pose_keypoints_override_aspect_ratio():
    eng = SituationEngine()
    upright_kp = {"left_shoulder": (120, 130), "right_shoulder": (140, 130), "left_hip": (122, 200), "right_hip": (138, 200)}
    lying_kp = {"left_shoulder": (80, 250), "right_shoulder": (80, 270), "left_hip": (180, 252), "right_hip": (180, 268)}
    # 박스는 정사각형 비슷(비율로는 판단 애매)이지만 키포인트상 몸통이 수평
    eng.update(frame(0.0, Person(1, STANDING, keypoints=upright_kp)))
    events = []
    for i in range(12):
        events += eng.update(frame(0.4 + i * 0.2, Person(1, (60, 200, 200, 300), keypoints=lying_kp)))
    assert types(events) == [EventType.FALL]


# ---- 넘어진 뒤 AI 인식이 끊기는 경우 (실제 영상에서 흔함) ----
SIZE = (640, 360)
WALK = (300, 100, 360, 280)  # 화면 가운데 서 있음


def lost_seq(eng, before, after_frames, tail_until):
    """before: [(t, bbox)] 인식된 구간, 이후 tail_until 초까지 아무도 인식되지 않음."""
    events = []
    for t, b in before:
        events += eng.update(FrameResult(CAM, t, [Person(1, b)], frame_size=SIZE))
    t = before[-1][0]
    while t < tail_until:
        t += 0.2
        events += eng.update(FrameResult(CAM, t, [], frame_size=SIZE))
    return events


def test_fall_motion_then_lost_is_fall_then_unresponsive():
    eng = SituationEngine(SituationConfig(immobile_sec=8))
    seq = [(t * 0.2, WALK) for t in range(15)]  # 3초 서 있음
    seq += [(3.0, (290, 140, 380, 280)), (3.2, (280, 190, 400, 285))]  # 옆으로 넓어지며 내려감
    events = lost_seq(eng, seq, None, 14)
    assert types(events) == [EventType.FALL, EventType.UNRESPONSIVE]
    assert "인식 끊김" in events[0].message
    assert events[0].timestamp <= 3.2 + 0.6 + 0.2  # 끊긴 지 0.6초 만에 판정
    assert events[1].emergency == "119"


def test_walking_out_of_frame_is_not_a_fall():
    eng = SituationEngine()
    seq = [(t * 0.2, (300 + t * 20, 100, 360 + t * 20, 280)) for t in range(15)]  # 오른쪽으로 걸어 나감
    seq += [(3.0, (580, 140, 640, 280))]  # 화면 끝에 닿은 채로 사라짐 (몸이 잘려 박스가 작아짐)
    assert lost_seq(eng, seq, None, 10) == []


def test_lost_without_fall_motion_is_not_a_fall():
    eng = SituationEngine()
    seq = [(t * 0.2, WALK) for t in range(15)]  # 서 있다가 그대로 가려짐 (기둥 뒤 등)
    assert lost_seq(eng, seq, None, 10) == []


def test_person_reappearing_upright_cancels_lost_fall():
    eng = SituationEngine(SituationConfig(immobile_sec=8))
    seq = [(t * 0.2, WALK) for t in range(15)] + [(3.2, (280, 190, 400, 285))]
    events = lost_seq(eng, seq, None, 5)
    assert types(events) == [EventType.FALL]
    # 같은 자리에서 새 추적 번호로 다시 서 있는 모습이 잡힘 → 일어난 것
    for i in range(50):
        events += eng.update(FrameResult(CAM, 5.2 + i * 0.2, [Person(9, WALK)], frame_size=SIZE))
    assert types(events) == [EventType.FALL]
