from app.dispatcher import EmergencyDispatcher, IncidentStatus
from app.situation import Event, EventType, Severity


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class RecordingChannel:
    name = "rec"

    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def send(self, incident, message):
        self.sent.append(message)
        return self.ok


def critical(track_id=1):
    return Event("cam01", EventType.UNRESPONSIVE, Severity.CRITICAL, "쓰러진 후 무반응", 1000.0, track_id, emergency="119")


def make(ch, clock):
    return EmergencyDispatcher([ch], countdown_sec=15, site_name="1공구", camera_names={"cam01": "정문"}, clock=clock)


def test_auto_dispatch_after_countdown():
    clock, ch = Clock(), RecordingChannel()
    d = make(ch, clock)
    inc = d.escalate(critical())
    clock.t += 14
    assert d.tick() == [] and inc.status == IncidentStatus.PENDING
    clock.t += 1
    d.tick()
    assert inc.status == IncidentStatus.DISPATCHED and inc.resolved_by == "auto"
    assert len(ch.sent) == 1 and "정문" in ch.sent[0] and "1공구" in ch.sent[0]


def test_operator_cancel_prevents_dispatch():
    clock, ch = Clock(), RecordingChannel()
    d = make(ch, clock)
    inc = d.escalate(critical())
    d.cancel(inc.id)
    clock.t += 60
    d.tick()
    assert inc.status == IncidentStatus.CANCELLED and ch.sent == []


def test_operator_confirm_dispatches_immediately():
    clock, ch = Clock(), RecordingChannel()
    d = make(ch, clock)
    inc = d.escalate(critical())
    d.confirm(inc.id)
    assert inc.status == IncidentStatus.DISPATCHED and inc.resolved_by == "operator"


def test_duplicate_pending_event_reuses_incident():
    d = make(RecordingChannel(), Clock())
    first = d.escalate(critical())
    assert d.escalate(critical()) is first
    assert d.escalate(critical(track_id=2)) is first  # 추적 번호가 바뀌어도 같은 카메라면 같은 사건


def test_non_emergency_event_is_ignored():
    d = make(RecordingChannel(), Clock())
    ev = Event("cam01", EventType.NO_HELMET, Severity.WARNING, "안전모 미착용", 0.0, 1)
    assert d.escalate(ev) is None


def test_fall_opens_incident_and_unresponsive_upgrades_it():
    clock, ch = Clock(), RecordingChannel()
    d = make(ch, clock)
    fall = Event("cam01", EventType.FALL, Severity.DANGER, "쓰러짐 감지", 1000.0, 1, emergency="119")
    inc = d.escalate(fall)
    assert inc is not None and inc.status == IncidentStatus.PENDING  # 쓰러지는 즉시 신고 창
    clock.t += 8
    same = d.escalate(critical(track_id=5))  # 8초 뒤 무반응 확인 (추적 번호가 바뀌어도)
    assert same is inc and inc.event.type == EventType.UNRESPONSIVE
    assert inc.deadline == 1000.0 + 15  # 카운트다운은 처음 쓰러진 시점 기준 그대로
    clock.t += 7
    d.tick()
    assert inc.status == IncidentStatus.DISPATCHED and "무반응" in ch.sent[0]


def test_ai_assessment_is_attached_and_added_to_report():
    clock, ch = Clock(), RecordingChannel()
    d = make(ch, clock)
    inc = d.escalate(critical())
    d.attach_ai(inc.id, {"severity": "높음", "call": "119", "reason": "바닥에 누워 움직임 없음", "report": "작업자 1명 쓰러져 의식 없음 추정"})
    d.confirm(inc.id)
    assert "AI 상황 판단: 작업자 1명 쓰러져 의식 없음 추정" in ch.sent[0]
    assert inc.to_dict()["ai"]["call"] == "119"


def test_all_channels_failed_marks_failed():
    clock = Clock()
    d = make(RecordingChannel(ok=False), clock)
    inc = d.escalate(critical())
    d.confirm(inc.id)
    assert inc.status == IncidentStatus.FAILED
