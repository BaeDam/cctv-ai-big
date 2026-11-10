# 인수인계 — 다음 세션에서 이어서 작업하기

마지막 정리: 2026-11-11 (로컬 세션). 지금까지 한 일·결정·다음 할 일을 정리한 문서입니다.
새 세션을 열면 Claude 에게 "docs/HANDOFF.md 읽고 이어서 작업해줘" 라고 말하면 됩니다.

## 프로젝트
- 이름: **지켜봄** (팀 빅 ai tv · 배찬익, 김태일, 윤성빈 · 동명대학교 인공지능학과)
- 한 줄 소개: “보는 CCTV에서, 지켜주는 CCTV로” — AI가 CCTV를 대신 보고, 판단하고, 112·119 호출까지 이어주는 관제 에이전트
- 저장소: https://github.com/BaeDam/cctv-ai-big (작업 브랜치 `claude/cctv-ai-agent-n2xy5n`, 기본 브랜치)
- 사이트: https://baedam.github.io/cctv-ai-big/ (`web-demo/` 를 올리면 GitHub Actions 가 자동 배포)

## 폴더
| 폴더 | 내용 |
|---|---|
| `web-demo/` | **지금 주력.** 서버 없이 브라우저에서 AI가 도는 16분할 관제 화면 (GIF 15개 + 웹캠) |
| `backend/` | Python 서버 버전 (FastAPI, YOLO, 상황 판단, 신고). 테스트 `cd backend && python -m pytest` |
| `frontend/` | 서버 버전용 관제 화면 |
| `docs/` | 구상서, 맥 설치, AI 테스트 결과, 이 문서 |

## web-demo 구조 (index.html 한 파일)
- AI 실행: onnxruntime-web 1.20.1 — `ort.webgpu.min.js`, `ort-jsep.js`, `runtime-jsep.gz.wasm` 모두 **사이트에서 직접 제공** (CDN 안 씀, npm 공식 파일과 동일 확인). WebGPU 우선 → 없으면 CPU 워커 병렬
- 보안: `<meta http-equiv="Content-Security-Policy">` 로 사이트 밖 연결 차단. 외부 주소를 새로 쓰면 CSP 도 고쳐야 함
- 모델: `model-pose640.gz.wasm` (YOLO11n-pose, 사람·관절), `model-ppe640.gz.wasm` (안전모 감지 YOLOv8, CC BY 4.0 데이터)
  - 파일은 gzip 압축된 ONNX (서빙 형식 때문에 이름만 .wasm)
- GIF 해석기 직접 구현 (`parseGif`, `lzw`, `GifPlayer`) → 프레임 단위로 AI 에 전달
- 판단 (`Engine`): 쓰러짐(1초 안 누움 → 1초 유지) → 무반응(8초) → 119, 넘어진 직후 인식 끊김 보완 규칙
- 싸움 (`fightUpdate`): 몸이 겹친(IoU>0.05) 2명의 빠른 팔 움직임, 분석 간격에 맞춰 기준 조절.
  1차 '확인 필요', 15초 안에 재감지 시 112 신고 창
- 안전모 (`runPpe`, `helmetAssign`): 공사장·웹캠 화면만 1.5초마다 검사, 머리 위치와 Hardhat/NO-Hardhat 박스 매칭
- 동작 학습 (`learn`, `gestureUpdate`): 관절 17개 움직임을 2초 창으로 기록·저장(localStorage), 거리 비교로 인식.
  기본은 기록한 카메라에서만, 움직임 크기 비교
- 기록: 이벤트를 localStorage 에 쌓고 CSV 내보내기

## 측정해 둔 성능 (정직하게)
- 쓰러짐: 실제 낙상 CCTV 영상 5개 중 4개, 넘어진 뒤 0.6~1.8초 (`docs/AI_TEST.md`)
- 싸움: 공개 싸움 데이터셋 50+50개 기준 약 20% 감지, 평상시 오탐 약 2% → **규칙 기반 한계, 전용 모델 필요**
- 안전모: 공사장 GIF 전원 착용 판정, 미착용 웹캠 영상 감지

## 내 PC 에서 실행
- 사이트로: https://baedam.github.io/cctv-ai-big/ (웹캠은 주소창 권한 허용)
- 로컬로: `web-demo/start-windows.bat` (윈도우, Python 필요) 또는 `sh web-demo/start-mac.sh` → http://localhost:8000
- 서버 버전: `docs/MAC_SETUP.md`. 외부 AI(Gemini 등)·API 키 없이 동작 (2026-11 Gemini 연동 제거, 키도 폐기)
- 키 유출 방지: 새 PC 에서 처음 한 번 `git config core.hooksPath .githooks` 실행 →
  커밋할 때 API 키 패턴이나 `.env` 파일이 들어 있으면 `.githooks/pre-commit` 이 커밋을 막음

## 2026-11-11 세션에서 한 일·결정
- **Gemini 연동 완전 제거** (서버 코드·설정·화면·문서). 키는 Google 에서 폐기함. 이유: 비용·지연·영상 외부 전송 문제, 판단 핵심은 YOLO+규칙
- **보안**: CDN 제거 + CSP, 서버·로컬 실행 `127.0.0.1` 전용, Ultralytics 통계 전송 끔, 커밋 전 비밀키 검사 훅(`.githooks/pre-commit`)
- **비용 점검**: 유료 서비스 없음. GitHub 은 Free 요금제·결제수단 미등록 확인 → 친구가 사이트 써도 0원
- **라이선스**: YOLO 는 AGPL-3.0 → 공개 저장소·공모전은 무료, 상업화 시 소스 공개 또는 유료 라이선스 (README 표 참고)
- 실제 사이트에서 GPU·CPU 둘 다 AI 정상, 외부 요청 0건 확인. **웹캠은 CSP 적용 후 아직 직접 확인 안 함**

## 참고한 예시: WatchOut (삼성 SSAFY 13기 우수상, 건설현장 안전관제)
- 웹·모바일·스마트워치 + AWS/Kafka/Spring 대규모 구성 (서버비 발생)
- 쓰러짐은 **스마트워치**로 감지 (CCTV 아님), '중장비 위험'은 장비가 화면에 보이면 알림 (거리 계산 없음)
- 우리 차별점: 워치 없이 CCTV만으로 쓰러짐 감지, 설치·서버비 0원, 영상 외부 전송 없음
- 가져올 만한 것: 구역 관리, 사건 증거 사진/영상, 위반 통계 대시보드

## 다음 할 일 후보
**화면 개선 (작고 효과 큼)**
1. 신고 창에 '지금 화면' 대신 **감지된 순간 사진**을 크게 고정 (반복 GIF 라 창을 열면 이미 일어서 있음)
2. 집중 분석 대상이 아닌 칸의 `AI 0.0fps` → `대기` 로 표시 (고장처럼 보임)
3. 타일 위 글자 줄이기 (평소엔 테두리 색+이름만, 나머지는 마우스 올리면)
4. 신고 처리 결과(취소/자동/즉시)를 화면에 크게 잠깐 표시

**차별화 기능**
5. **침대·바닥 구역 그리기** (요양병원: 침대 안에서 눕는 건 정상 → 오탐 감소)
6. **사건 증거 영상** (감지 전후 5초 자동 저장·내려받기)
7. 개인정보 보호 화면 (사람 대신 관절 뼈대만 표시)
8. 신고 문장 자동 작성 + 음성 읽기 (Gemini 없이 템플릿 + 브라우저 음성)

**AI 성능**
9. 폭행 전용 학습 모델 (Aktı et al. 2019 데이터셋, MIT) — 현재 감지율 약 20% 가 가장 큰 약점
10. 화재·연기 감지 모델
11. 실제 웹캠으로 동작 학습·폭행 연기 테스트 후 기준값 조정

## 영상·모델 출처
- 공공장소 GIF: Surveillance Camera Fight Dataset (Ş. Aktı et al., IPTA 2019, MIT)
- 요양병원 GIF: github.com/ambianic/fall-detection
- 공사장 GIF: 공개 PPE 저장소 샘플 ppe-1~3
- 안전모 모델: github.com/snehilsanyal/Construction-Site-Safety-PPE-Detection (Roboflow Construction Site Safety, CC BY 4.0)
