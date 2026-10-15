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
    ev = Event("cam01", EventType.FALL, Severity.DANGER, "쓰러짐", 0.0, 1)
    assert d.escalate(ev) is None


def test_all_channels_failed_marks_failed():
    clock = Clock()
    d = make(RecordingChannel(ok=False), clock)
    inc = d.escalate(critical())
    d.confirm(inc.id)
    assert inc.status == IncidentStatus.FAILED
