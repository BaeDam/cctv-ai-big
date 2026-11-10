# 지켜봄 — 보는 CCTV에서, 지켜주는 CCTV로

AI가 CCTV 화면을 대신 보고, 사람이 쓰러지거나 싸움이 나면 상황을 판단해
**112·119 신고 절차**까지 이어주는 관제 시스템입니다.

**팀 빅 ai tv** · 배찬익, 김태일, 윤성빈 · 동명대학교 인공지능학과

설치·서버 없이 크롬에서 열리고, AI는 **내 컴퓨터 브라우저 안에서만** 돌아 영상이 밖으로 나가지 않습니다.

---

## 무엇을 하나요
| 감지 | 방식 | 이어지는 조치 |
|---|---|---|
| 쓰러짐 → 무반응 | 관절 17개 자세 + 시간 흐름 (누움 1초 → 8초 무반응) | 신고 창 → 15초 안에 취소 없으면 **119** 자동 신고 |
| 싸움·폭행 의심 | 몸이 겹친 2명의 빠른 팔 움직임 | 1차 '확인 필요', 15초 안에 다시 잡히면 **112** 신고 창 |
| 안전모 미착용 | 안전모 감지 모델 + 머리 위치 | 주의 알림 |
| 학습 동작 | 내가 웹캠으로 기록한 동작을 관절 움직임으로 비교 | 정한 대로 (알림 / 112 / 119) |

- **16분할 관제 화면**: 공사장 3 · 요양병원 5 · 공공장소 7 현장 영상 + 웹캠 / 내 영상
- 위험도별 테두리 색, 이벤트 목록, 클릭하면 확대, 기록 CSV 저장
- GPU(WebGPU)가 있으면 GPU로, 없으면 CPU로 자동 실행
- 신고는 **시연 모드**입니다. 실제 112·119로 발송되지 않습니다.

## 측정한 성능 (정직하게)
| 감지 | 결과 | 비고 |
|---|---|---|
| 쓰러짐 | 실제 낙상 CCTV 영상 **5개 중 4개**, 넘어진 뒤 0.6~1.8초 | [`docs/AI_TEST.md`](docs/AI_TEST.md) |
| 싸움 | 공개 싸움 영상 50+50개 기준 **약 20%** 감지, 평상시 오탐 약 2% | 규칙 기반 한계 → 전용 모델 필요 |
| 안전모 | 공사장 영상 착용 판정, 미착용 웹캠 영상 감지 | |

## 구성
| 폴더 | 내용 |
|---|---|
| [`web-demo/`](web-demo/) | **주력.** 서버 없이 브라우저에서 AI가 도는 관제 화면. 설명: [`web-demo/README.md`](web-demo/README.md) |
| `backend/` | 서버 버전 (Python FastAPI + YOLO, 실제 IP 카메라 RTSP 연결용) |
| `frontend/` | 서버 버전용 관제 화면 |
| `docs/` | [구상서](docs/PLAN.md) · [맥 설치](docs/MAC_SETUP.md) · [AI 테스트 결과](docs/AI_TEST.md) · [인수인계](docs/HANDOFF.md) |

## 내 PC에서 실행
**브라우저 버전 (추천)** — 저장소를 내려받아:
- 윈도우: `web-demo/start-windows.bat` 더블클릭 (Python 필요)
- 맥: `sh web-demo/start-mac.sh`
- → 크롬에서 http://localhost:8000

**서버 버전** — 실제 카메라(RTSP·웹캠)를 연결할 때. 자세한 건 [`docs/MAC_SETUP.md`](docs/MAC_SETUP.md)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
`backend/config.yaml` 의 카메라 `source` 에 RTSP 주소, 영상 파일, 웹캠 번호(`0`)를 넣습니다.

**테스트**
```bash
cd backend
pip install -r requirements-dev.txt fastapi pyyaml
python -m pytest
```

> ⚠️ 신고 채널 기본값은 `mock`(로그만 남김)입니다. 112·119 직접 자동 연동은 오신고 문제로
> 관할 기관 협의가 필요하며, 우선 현장 관리자 문자·관제업체 webhook 연동을 권장합니다.

## 보안·비용
- **0원으로 운영.** 유료 서비스·API 키·결제 수단 없음. 외부 AI(Gemini) 연동은 2026-11 제거했습니다.
- **영상이 밖으로 나가지 않음.** AI 모델과 실행기를 외부 CDN 없이 직접 제공하고, 보안 정책(CSP)으로 외부 연결 자체를 막습니다.
- **서버 버전은 이 PC에서만 접속**(`127.0.0.1`). 로그인 기능이 없으므로 와이파이 전체에 열지 마세요.
- YOLO(Ultralytics) 사용 통계 전송을 꺼 둡니다.
- 비밀키 유출 방지: 처음 한 번 `git config core.hooksPath .githooks` → 키나 `.env` 가 든 커밋을 자동 차단

## 라이선스·출처
| 구성 요소 | 라이선스 | 주의 |
|---|---|---|
| Ultralytics YOLO11n-pose (사람·관절) | AGPL-3.0 | 소스 공개 저장소에서는 무료. **상업 서비스로 팔 때는 소스 공개 또는 Ultralytics 유료 라이선스 필요** |
| 안전모 모델 (snehilsanyal/Construction-Site-Safety-PPE-Detection, YOLOv8) | AGPL-3.0, 학습 데이터 Roboflow Construction Site Safety CC BY 4.0 | 출처 표기 필요 |
| onnxruntime-web 1.20.1 | MIT | |
| 공공장소 영상: Surveillance Camera Fight Dataset (Ş. Aktı et al., IPTA 2019) | MIT | |
| 요양병원 영상: github.com/ambianic/fall-detection | 원 저장소 라이선스 따름 | |
| 공사장 영상: 공개 PPE 감지 저장소 샘플 (ppe-1~3) | 원 저장소 라이선스 따름 | |
