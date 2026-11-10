# 브라우저 AI 관제 데모 (서버 없이 동작)

## 크롬에서 바로 열기 (웹캠 사용 가능)
- **사이트 주소:** https://baedam.github.io/cctv-ai-big/
  - 처음 한 번: 저장소 **Settings → Pages → Build and deployment → Source: GitHub Actions** 선택
  - 이후 `web-demo/` 를 고쳐서 올리면 사이트가 자동으로 갱신됨
- **내 PC에서 열기:** 이 폴더를 내려받아
  - 윈도우: `start-windows.bat` 더블클릭 (Python 필요) → 크롬에서 http://localhost:8000
  - 맥: 터미널에서 `sh start-mac.sh`
- 웹캠: 16번 칸 **📷 웹캠 연결** → 주소창에 뜨는 카메라 권한 **허용**

## 동작 학습
1. 오른쪽 **동작 학습** 탭에서 카메라(웹캠) 선택, 동작 이름·위험도·호출(없음/112/119)·길이 입력
2. **● 샘플 기록** → 3초 카운트다운 뒤 동작. 같은 동작을 3~5번 반복
3. **저장** → 이후 같은 동작이 나오면 "학습 동작 인식" 이벤트와 알림·신고 흐름
- 관절 17개의 움직임을 저장해 비교하는 방식(딥러닝 재학습 아님). 손 흔들기·팔 들기처럼 뚜렷한 동작이 잘 맞음
- 기본은 **기록한 카메라에서만** 인식 (다른 화면 오인식 방지). 움직임 크기도 비교
- 저장한 동작은 브라우저에 남고, **내보내기/가져오기**로 친구와 JSON 파일 공유
- 감지 기록은 이벤트 탭의 **기록 CSV** 로 내려받기

AI 모델(YOLO11n-pose)을 브라우저 안에서 직접 돌리는 16분할 관제 화면입니다.
판단 규칙은 `backend/app/situation.py` 와 같습니다.

## 기능
- 15개 현장 GIF(공사장 3 · 요양병원 5 · 공공장소 7)를 동시에 분석, 16번째 칸은 내 영상 추가
- GIF 해석기 내장: 프레임을 직접 풀어 AI에 넘김 (브라우저 기본 GIF 재생에 의존하지 않음)
- 현장 필터, 카메라 목록·상태, 알림 화면 맨 앞으로, 타일 드래그로 순서 변경
- 카메라별 AI 켜기·끄기, 보이는 화면 우선 분석, 절전 모드
- 쓰러짐 → 즉시 신고 창 → 무반응 격상 → 15초 후 자동 신고(시연 모드)
- 단축키: ←/→ 페이지, 1·4·9·6 분할, Enter 확대, Space AI, ? 도움말
- GPU(WebGPU)가 있으면 GPU로, 없으면 CPU(WebAssembly, 코어별 병렬)로 실행

## 감지 종류
| 종류 | 방식 | 신고 | 확인한 성능 |
|---|---|---|---|
| 쓰러짐 → 무반응 | 자세 + 시간 흐름 규칙 | 119 | 실제 낙상 영상 5개 중 4개 |
| 싸움·폭행 의심 | 몸이 겹친 2명의 빠른 팔 움직임 (분석 속도에 맞춰 기준 조절) | 1차 '확인 필요' 알림, 15초 안에 재감지 시 112 | 공개 싸움 영상 50+50개 기준 약 20% 감지, 평상시 오탐 약 2% |
| 안전모 미착용 | 안전모 감지 모델 + 머리 위치 | 주의 알림 | 공사장 GIF 전원 착용 판정, 미착용 웹캠 영상 감지 |
| 학습 동작 | 관절 움직임 기록·비교 | 설정한 대로 | 가짜 웹캠으로 기록·인식 확인 |

## 현재 한계
- 폭행은 규칙 기반이라 놓치는 경우가 많음 → 폭행 전용 학습 모델 필요
- 화재·연기 감지 없음

## AI 모델 파일 (저장소에 포함, 사이트에서 바로 사용)
| 파일 | 만든 방법 |
|---|---|
| `model-pose640.gz.wasm` | `yolo export model=yolo11n-pose.pt format=onnx imgsz=640 opset=17 simplify=True` 후 `gzip -9` (이름만 .wasm) |
| `model-ppe640.gz.wasm` | 공개 안전모 감지 모델(github.com/snehilsanyal/Construction-Site-Safety-PPE-Detection, Roboflow Construction Site Safety 데이터 CC BY 4.0로 학습된 YOLOv8)을 ONNX로 변환 후 `gzip -9` |
| `runtime-jsep.gz.wasm` | npm `onnxruntime-web@1.20.1` 의 `dist/ort-wasm-simd-threaded.jsep.wasm` 을 `gzip -9` |

## 영상 출처
- 공공장소(`pub_*.gif`): Surveillance Camera Fight Dataset — Ş. Aktı et al., "Vision-based Fight Detection from Surveillance Cameras", IPTA 2019 (MIT License), github.com/seymanurakti/fight-detection-surv-dataset
- 요양병원(`care*.gif`): github.com/ambianic/fall-detection `videos/` (무반응 판정 확인용으로 마지막 장면 연장)
- 공사장(`site*.gif`): 공개 PPE 감지 저장소의 샘플 영상 ppe-1~3 (github.com/ishita126jain/PPE-Detection 등)
