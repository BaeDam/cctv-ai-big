# 브라우저 AI 관제 데모 (서버 없이 동작)

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

## 현재 한계
- 싸움·폭행, 안전모 미착용, 화재 판단은 아직 없음 (사람 인식과 쓰러짐만)

## 같이 있어야 하는 파일 (용량 때문에 저장소에 넣지 않음)
| 파일 | 만드는 방법 |
|---|---|
| `model-pose640.gz.wasm` | `yolo export model=yolo11n-pose.pt format=onnx imgsz=640 opset=17 simplify=True` 후 `gzip -9` (이름만 .wasm) |
| `runtime-jsep.gz.wasm` | npm `onnxruntime-web@1.20.1` 의 `dist/ort-wasm-simd-threaded.jsep.wasm` 을 `gzip -9` |

## 영상 출처
- 공공장소(`pub_*.gif`): Surveillance Camera Fight Dataset — Ş. Aktı et al., "Vision-based Fight Detection from Surveillance Cameras", IPTA 2019 (MIT License), github.com/seymanurakti/fight-detection-surv-dataset
- 요양병원(`care*.gif`): github.com/ambianic/fall-detection `videos/` (무반응 판정 확인용으로 마지막 장면 연장)
- 공사장(`site*.gif`): 공개 PPE 감지 저장소의 샘플 영상 ppe-1~3 (github.com/ishita126jain/PPE-Detection 등)
