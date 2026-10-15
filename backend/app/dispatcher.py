"""긴급 신고 에스컬레이션.

긴급(critical) 이벤트가 오면 바로 신고하지 않고 '사건(Incident)'을 만든 뒤
카운트다운 동안 관리자가 취소/즉시 신고를 고를 수 있게 한다.
아무 응답이 없으면 카운트다운이 끝나는 순간 자동으로 신고 채널에 발송한다.

신고 채널은 어댑터로 분리되어 있다.
  - mock    : 로그만 남김 (시연/개발 기본값)
  - webhook : 보안·관제업체 또는 사내 시스템으로 JSON POST
  - sms     : 문자 발송 서비스 연동 자리 (공급사 API 키 필요)
실제 112/119 직접 연동은 관할 기관과 협의 후 활성화해야 한다 (docs/PLAN.md 참고).
"""

from __future__ import annotations

import itertools
import json
import logging
import time
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol

from .situation import Event

log = logging.getLogger("dispatcher")


class IncidentStatus(str, Enum):
    PENDING = "pending"  # 카운트다운 중
    CANCELLED = "cancelled"  # 관리자가 오탐으로 취소
    DISPATCHED = "dispatched"  # 신고 완료
    FAILED = "failed"  # 모든 채널 발송 실패


@dataclass
class Incident:
    id: int
    event: Event
    target: str  # "119" / "112"
    created_at: float
    deadline: float
    status: IncidentStatus = IncidentStatus.PENDING
    resolved_by: str | None = None  # "auto" / "operator"
    log: list[str] = field(default_factory=list)
    ai: dict | None = None  # AI 에이전트(Gemini) 판단 결과. {"pending": True} 면 판단 중

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "event": self.event.to_dict(),
            "target": self.target,
            "created_at": self.created_at,
            "deadline": self.deadline,
            "status": self.status.value,
            "resolved_by": self.resolved_by,
            "log": self.log,
            "ai": self.ai,
        }


class Channel(Protocol):
    name: str

    def send(self, incident: Incident, message: str) -> bool: ...


class MockChannel:
    name = "mock"

    def send(self, incident: Incident, message: str) -> bool:
        log.warning("[MOCK %s 신고] %s", incident.target, message)
        return True


class WebhookChannel:
    name = "webhook"

    def __init__(self, url: str, timeout: float = 5.0):
        self.url, self.timeout = url, timeout

    def send(self, incident: Incident, message: str) -> bool:
        body = json.dumps({"message": message, **incident.to_dict()}, ensure_ascii=False).encode()
        req = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except OSError as exc:
            log.error("webhook 발송 실패: %s", exc)
            return False


class SmsChannel:
    """문자 발송 공급사(예: 알리고, NHN Cloud, Twilio) 연동 자리."""

    name = "sms"

    def __init__(self, recipients: list[str]):
        self.recipients = recipients

    def send(self, incident: Incident, message: str) -> bool:
        # TODO: 계약한 문자 공급사 API 호출로 교체
        log.warning("[SMS 미연동] 수신자=%s 내용=%s", self.recipients, message)
        return False


class EmergencyDispatcher:
    def __init__(
        self,
        channels: list[Channel],
        countdown_sec: float = 15.0,
        site_name: str = "현장",
        site_address: str = "",
        camera_names: dict[str, str] | None = None,
        on_change: Callable[[Incident], None] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.channels = channels
        self.countdown_sec = countdown_sec
        self.site_name = site_name
        self.site_address = site_address
        self.camera_names = camera_names or {}
        self.on_change = on_change
        self.clock = clock
        self.incidents: dict[int, Incident] = {}
        self._ids = itertools.count(1)

    def escalate(self, event: Event) -> Incident | None:
        if not event.emergency:
            return None
        # 같은 카메라에서 같은 계열(쓰러짐→무반응 등)로 대기 중인 사건이 있으면 새로 만들지 않고,
        # 더 심각한 내용이면 그 사건을 격상한다
        # (쓰러진 사람은 AI 추적 번호가 바뀌기 쉬워서 사람 단위가 아니라 카메라 단위로 묶는다)
        for inc in self.incidents.values():
            if (
                inc.status == IncidentStatus.PENDING
                and inc.event.camera_id == event.camera_id
                and _family(inc.event.type) == _family(event.type)
            ):
                if _rank(event) > _rank(inc.event):
                    inc.event = event
                    inc.log.append(f"격상: {event.message}")
                    self._notify(inc)
                return inc
        now = self.clock()
        inc = Incident(
            id=next(self._ids),
            event=event,
            target=event.emergency,
            created_at=now,
            deadline=now + self.countdown_sec,
        )
        inc.log.append(f"사건 생성, {self.countdown_sec:.0f}초 후 자동 신고")
        self.incidents[inc.id] = inc
        self._notify(inc)
        return inc

    def attach_ai(self, incident_id: int, result: dict) -> None:
        inc = self.incidents.get(incident_id)
        if inc is None:
            return
        inc.ai = result
        if "error" not in result and not result.get("pending"):
            inc.log.append(f"AI 판단: {result.get('severity')} / {result.get('call')} — {result.get('reason')}")
        self._notify(inc)

    def cancel(self, incident_id: int, by: str = "operator") -> Incident | None:
        inc = self.incidents.get(incident_id)
        if inc and inc.status == IncidentStatus.PENDING:
            inc.status, inc.resolved_by = IncidentStatus.CANCELLED, by
            inc.log.append(f"{by} 취소 (오탐)")
            self._notify(inc)
        return inc

    def confirm(self, incident_id: int, by: str = "operator") -> Incident | None:
        inc = self.incidents.get(incident_id)
        if inc and inc.status == IncidentStatus.PENDING:
            self._dispatch(inc, by)
        return inc

    def tick(self) -> list[Incident]:
        """주기적으로 호출. 카운트다운이 끝난 사건을 자동 신고한다."""
        now = self.clock()
        done = []
        for inc in list(self.incidents.values()):
            if inc.status == IncidentStatus.PENDING and now >= inc.deadline:
                self._dispatch(inc, "auto")
                done.append(inc)
        return done

    def build_message(self, inc: Incident) -> str:
        ev = inc.event
        cam = self.camera_names.get(ev.camera_id, ev.camera_id)
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ev.timestamp))
        kind = "구급/화재" if inc.target == "119" else "경찰 출동"
        msg = (
            f"[CCTV AI 자동신고·{kind} 요청] {ev.message}\n"
            f"장소: {self.site_name} {self.site_address} / 카메라: {cam}\n"
            f"발생: {when}"
        )
        if inc.ai and inc.ai.get("report"):
            msg += f"\nAI 상황 판단: {inc.ai['report']}"
        return msg

    def _dispatch(self, inc: Incident, by: str) -> None:
        message = self.build_message(inc)
        sent = [ch.name for ch in self.channels if _safe_send(ch, inc, message)]
        inc.resolved_by = by
        if sent:
            inc.status = IncidentStatus.DISPATCHED
            inc.log.append(f"{inc.target} 신고 발송 ({by}): {', '.join(sent)}")
        else:
            inc.status = IncidentStatus.FAILED
            inc.log.append(f"{inc.target} 신고 실패 — 모든 채널 발송 실패")
        self._notify(inc)

    def _notify(self, inc: Incident) -> None:
        if self.on_change:
            self.on_change(inc)


_FAMILY = {"fall": "person_down", "unresponsive": "person_down", "fire": "fire", "smoke": "fire"}
_SEVERITY_RANK = {"info": 0, "warning": 1, "danger": 2, "critical": 3}


def _family(etype) -> str:
    return _FAMILY.get(etype.value, etype.value)


def _rank(ev: Event) -> int:
    return _SEVERITY_RANK.get(ev.severity.value, 0)


def _safe_send(ch: Channel, inc: Incident, message: str) -> bool:
    try:
        return ch.send(inc, message)
    except Exception:  # 채널 하나가 죽어도 다른 채널은 시도
        log.exception("%s 채널 오류", ch.name)
        return False
