# 브라우저 AI 데모 (서버 없이 동작)

AI 모델(YOLO11n-pose)을 브라우저 안에서 직접 돌리는 관제 화면입니다.
판단 규칙은 `backend/app/situation.py` 와 같습니다.

- GPU(WebGPU)가 있으면 GPU로, 없으면 CPU(WebAssembly, 코어별 병렬)로 실행
- 샘플 영상 4개 + "내 영상으로 테스트"로 영상 파일 추가 가능
- 신고는 시연 모드 (실제 발송 없음)

## 같이 있어야 하는 파일 (저장소에는 넣지 않음, 용량 문제)
| 파일 | 만드는 방법 |
|---|---|
| `model-pose640.gz.wasm` | `yolo export model=yolo11n-pose.pt format=onnx imgsz=640 opset=17 simplify=True` 후 `gzip -9` (이름만 .wasm) |
| `runtime-jsep.gz.wasm` | npm `onnxruntime-web@1.20.1` 의 `dist/ort-wasm-simd-threaded.jsep.wasm` 을 `gzip -9` |
| `cam2~5.mp4 / .webm` | 테스트할 영상 (H.264 MP4 + VP9 WebM) |
