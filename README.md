# CCTV AI 에이전트

현장 CCTV 화면을 한곳에서 보면서 AI가 위험 요소를 찾아 알려주고,
사람이 쓰러지거나 크게 다치면 상황을 판단해 **112/119 신고 절차**까지 이어주는 보조 관제 시스템입니다.

- 구상서·일정(~10/28): [`docs/PLAN.md`](docs/PLAN.md)
- 맥북(M4/M5) 설치·카메라 연결: [`docs/MAC_SETUP.md`](docs/MAC_SETUP.md)
- 실제 AI 감지 테스트 결과: [`docs/AI_TEST.md`](docs/AI_TEST.md)

## 주요 기능
- **분할 화면 직접 설정**: 1/4/9/16 분할 + 가로×세로 직접 입력 (브라우저에 저장)
- **클릭하면 확대**, 확대 화면에서 **◀ ▶ / 키보드 ←→ / 스와이프로 카메라 넘김**
- 카메라가 분할 수보다 많으면 그리드도 페이지 단위로 넘김
- AI 이벤트 패널, 위험도별 테두리 색 (주의·위험·긴급)
- **상황 판단**: 쓰러짐 → (1.5초 유지) 확정 → (10초 무반응) 긴급 → 119
  화재·연기 → 119, 폭행 → 112, 위험구역 진입·안전모 미착용 → 알림
- **긴급 신고 모달**: 15초 카운트다운 동안 `오탐 취소` / `즉시 신고`, 응답 없으면 자동 신고

## 바로 보기 (데모)
`frontend/index.html` 을 브라우저로 열면 가상 영상으로 동작합니다 (DEMO).
상단의 `상황 발생` 으로 쓰러짐/화재/폭행 등을 시연할 수 있습니다.

## 서버 실행 (LIVE)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
# http://localhost:8000 접속
```
`backend/config.yaml` 에서 카메라 `source` 에 RTSP 주소(예: `rtsp://user:pass@192.168.0.10:554/stream1`),
영상 파일 경로, 또는 웹캠 번호(`0`)를 넣으면 YOLO 분석이 시작됩니다.
비워둔 카메라는 데모 영상으로 표시됩니다.

## 테스트
```bash
cd backend
pip install -r requirements-dev.txt fastapi pyyaml
python -m pytest
```

## 구조
```
backend/
  app/situation.py   상황 판단 엔진 (쓰러짐 상태머신, 화재, 구역, 안전모) ★
  app/dispatcher.py  신고 에스컬레이션 (카운트다운, 취소, 자동 발송, mock/webhook/sms)
  app/detector.py    YOLO 포즈·추적·안전모·화재 인식
  app/stream.py      카메라별 영상 읽기 워커 + MJPEG
  app/main.py        FastAPI (REST, WebSocket, 프론트 제공)
  config.yaml        카메라·구역·임계값·신고 채널 설정
frontend/            관제 화면 (빌드 없이 실행)
docs/PLAN.md         구상서
```

> ⚠️ 신고 채널 기본값은 `mock`(로그만 남김)입니다. 112/119 직접 자동 연동은 오신고 문제로
> 관할 기관 협의가 필요하며, 우선 현장 관리자 문자·관제업체 webhook 연동을 권장합니다.

## 보안·비용 원칙
- **유료 서비스·API 키 없음.** 외부 AI(Gemini 등) 연동은 제거했고, 모든 AI 는 내 PC·브라우저 안에서만 돕니다.
- **영상이 밖으로 나가지 않음.** 사이트(`web-demo`)는 AI 실행기까지 직접 제공하고, 보안 정책(CSP)으로 외부 연결 자체를 막습니다.
- **서버는 이 PC 에서만 접속**(`--host 127.0.0.1`). 로그인 기능이 없으므로 와이파이 전체에 열지 마세요.
- Ultralytics 사용 통계 전송은 꺼 둡니다 (`settings.sync=False`).
- 커밋 전 비밀키 검사: 처음 한 번 `git config core.hooksPath .githooks`

## 라이선스·출처
| 구성 요소 | 라이선스 | 주의 |
|---|---|---|
| Ultralytics YOLO11n-pose (사람·관절) | AGPL-3.0 | 소스 공개 저장소에서 쓰는 건 무료. **상업 서비스로 팔 때는 소스 공개 또는 Ultralytics 유료 라이선스 필요** |
| 안전모 모델 (snehilsanyal/Construction-Site-Safety-PPE-Detection, YOLOv8) | AGPL-3.0 (Ultralytics 기반), 학습 데이터 Roboflow Construction Site Safety CC BY 4.0 | 출처 표기 필요 |
| onnxruntime-web 1.20.1 | MIT | |
| 공공장소 GIF: Surveillance Camera Fight Dataset (Aktı et al., IPTA 2019) | MIT | |
| 요양병원 GIF: ambianic/fall-detection | 저장소 라이선스 따름 | |
