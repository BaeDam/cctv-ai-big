from app.agent import GeminiAgent, parse_response


def test_parse_valid_response():
    data = {"candidates": [{"content": {"parts": [{"text": '{"is_emergency": true, "severity": "높음", "call": "119", '
        '"observation": "사람이 바닥에 누워 있음", "reason": "움직임 없음", "report": "1명 쓰러짐"}'}]}}]}
    r = parse_response(data)
    assert r["is_emergency"] is True and r["call"] == "119" and r["report"] == "1명 쓰러짐"


def test_parse_broken_response():
    assert "error" in parse_response({"candidates": []})
    assert "error" in parse_response({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})


def test_no_key_means_disabled(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ag = GeminiAgent()
    assert not ag.enabled
    assert "error" in ag.assess([b"x"], "cam", "쓰러짐")
