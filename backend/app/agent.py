"""AI 에이전트 판단 (Gemini).

YOLO 가 '쓰러짐' 같은 이상 징후를 잡으면, 그 순간의 장면 사진을 Gemini 에 보내서
  - 실제 위험인지 / 오탐인지
  - 얼마나 심각한지, 112·119 중 어디인지
  - 신고·보고용 문장
을 받아온다. YOLO 는 항상 빠르게 돌고, Gemini 는 이상 징후가 있을 때만 부른다.

안전 원칙: Gemini 가 '오탐 같다'고 해도 신고 창을 자동으로 닫지 않는다.
판단 결과는 관리자에게 참고 정보로 보여주고, 취소는 사람이 한다.

API 키는 환경변수 GEMINI_API_KEY (backend/.env) 에서만 읽고, 로그·응답에 절대 남기지 않는다.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger("agent")

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

PROMPT = """당신은 공사·산업 현장 CCTV 안전 관제 요원입니다.
자동 감지 시스템이 아래 카메라에서 이상 징후를 감지했습니다.

- 카메라: {camera}
- 자동 감지 내용: {event}

첨부한 CCTV 장면을 보고 판단하세요.
- 사람이 실제로 쓰러져 있거나 다쳤는지, 단순히 앉거나 눕거나 물건을 줍는 등 정상 동작인지
- 영상에서 보이는 것만 근거로 하고, 보이지 않는 것은 추측하지 마세요
- 애매하면 위험한 쪽으로 판단하세요 (사람 안전이 우선)

JSON 으로만 답하세요."""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "is_emergency": {"type": "BOOLEAN", "description": "실제 위급 상황으로 보이면 true"},
        "severity": {"type": "STRING", "enum": ["낮음", "보통", "높음", "매우 높음"]},
        "call": {"type": "STRING", "enum": ["119", "112", "현장 확인", "없음"]},
        "observation": {"type": "STRING", "description": "장면에서 보이는 것 1~2문장"},
        "reason": {"type": "STRING", "description": "판단 근거 1문장"},
        "report": {"type": "STRING", "description": "신고 시 전달할 문장 1~2문장"},
    },
    "required": ["is_emergency", "severity", "call", "observation", "reason", "report"],
}


class GeminiAgent:
    def __init__(self, model: str = "gemini-flash-latest", timeout: float = 15.0, api_key: str | None = None):
        self.model = model
        self.timeout = timeout
        self._key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def assess(self, images: list[bytes], camera: str, event: str) -> dict:
        """장면 JPEG 들을 보고 판단. 실패해도 예외 대신 {'error': ...} 를 돌려준다."""
        if not self.enabled:
            return {"error": "GEMINI_API_KEY 가 설정되지 않음"}
        parts = [{"text": PROMPT.format(camera=camera, event=event)}]
        for img in images:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
                "responseSchema": RESPONSE_SCHEMA,
            },
        }
        req = urllib.request.Request(
            API_URL.format(model=self.model),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._key},
            method="POST",
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read()).get("error", {}).get("message", "")[:200]
            except Exception:
                pass
            log.error("Gemini 오류 %s %s", exc.code, detail)
            return {"error": f"Gemini 응답 오류 ({exc.code}) {detail}".strip()}
        except (OSError, ValueError) as exc:
            log.error("Gemini 연결 실패: %s", exc)
            return {"error": f"Gemini 연결 실패: {exc}"}
        result = parse_response(data)
        result["model"] = self.model
        result["elapsed_sec"] = round(time.time() - t0, 1)
        return result


def parse_response(data: dict) -> dict:
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        out = json.loads(text)
    except (KeyError, IndexError, TypeError, ValueError):
        return {"error": "Gemini 응답을 해석하지 못함"}
    return {k: out.get(k) for k in RESPONSE_SCHEMA["properties"]}
