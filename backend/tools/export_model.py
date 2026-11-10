"""AI 모델을 장비에 맞는 최고 속도 형식으로 변환한다.

    python tools/export_model.py            # 장비 자동 판단
    python tools/export_model.py --format coreml

  - 맥북(Apple Silicon) → CoreML  : Neural Engine 사용, 보통 PyTorch(mps)보다 빠름
  - NVIDIA GPU         → TensorRT : 가장 빠름 (TensorRT 설치 필요)
  - 인텔/AMD CPU       → OpenVINO : CPU에서 2~3배 빨라짐

변환이 끝나면 출력된 경로를 config.yaml 의 models.pose 에 넣으면 된다.
"""

import argparse
import platform


def auto_format() -> str:
    import torch

    if torch.cuda.is_available():
        return "engine"
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "coreml"
    return "openvino"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo11n-pose.pt")
    ap.add_argument("--format", default=None, help="coreml / engine / openvino / onnx")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    from ultralytics import YOLO, settings

    settings.update({"sync": False})  # 사용 통계 외부 전송 끄기

    fmt = args.format or auto_format()
    print(f"변환 형식: {fmt}")
    path = YOLO(args.model).export(format=fmt, imgsz=args.imgsz, half=fmt == "engine")
    print(f"\n완료 → config.yaml 의 models.pose 를 아래 값으로 바꾸세요:\n  pose: \"{path}\"")


if __name__ == "__main__":
    main()
