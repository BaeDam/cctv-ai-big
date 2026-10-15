# 맥북(M4/M5)에서 실행하기

맥북 Apple Silicon 칩의 GPU(mps)를 자동으로 사용합니다 (`config.yaml` → `models.device: auto`).

## 1. 처음 한 번 설치
터미널을 열고:

```bash
# 파이썬이 없으면 (Homebrew 설치 후)
brew install python@3.12

# 프로젝트 폴더로 이동
cd cctv-ai-big/backend

# 가상환경 만들고 켜기
python3.12 -m venv .venv
source .venv/bin/activate

# 패키지 설치 (PyTorch 맥 GPU 지원 포함, 몇 분 걸림)
pip install -r requirements.txt
```

맥 GPU를 쓸 수 있는지 확인:
```bash
python -c "import torch; print('맥 GPU 사용 가능:', torch.backends.mps.is_available())"
```
`True` 가 나오면 됩니다.

## 1-1. Gemini AI 에이전트 키 넣기 (선택)
쓰러짐이 감지되면 장면 사진을 Gemini가 보고 실제 위험인지, 심각도, 신고 문장을 판단해 신고 창에 보여줍니다.

```bash
cd cctv-ai-big/backend
cp .env.example .env
open -e .env        # GEMINI_API_KEY= 뒤에 키를 붙여넣고 저장
chmod 600 .env      # 본인만 읽을 수 있게
```
- `.env` 는 git 에 올라가지 않습니다. 키를 코드·설정 파일·채팅에 직접 쓰지 마세요.
- 키가 없거나 크레딧이 없어도 감지와 신고 창은 그대로 동작합니다 (AI 판단 칸에 사유만 표시).
- Gemini 가 '위급하지 않아 보임'이라고 해도 신고 창을 자동으로 닫지 않습니다. 취소는 사람이 합니다.

## 2. 맥북 내장 카메라로 테스트 (카메라 구매 전)
`backend/config.yaml` 에서 첫 번째 카메라의 `source` 를 `"0"` 으로 바꿉니다.

```yaml
  - { id: cam01, name: "정문 출입구", source: "0" }
```

실행:
```bash
cd cctv-ai-big/backend
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 처음 실행하면 AI 모델(`yolo11n-pose.pt`, 약 6MB)을 자동으로 받습니다.
- **카메라 권한**: "터미널이 카메라에 접근하려고 합니다" 창이 뜨면 허용.
  안 뜨고 영상이 안 나오면 `시스템 설정 → 개인정보 보호 및 보안 → 카메라` 에서 터미널을 켜고 다시 실행.
- 브라우저에서 http://localhost:8000 접속 → 첫 번째 칸이 실제 카메라 영상 + AI 박스로 나오면 성공.

### 쓰러짐 테스트
1. 카메라에서 2~3m 떨어져 **전신이 보이게** 섭니다.
2. 바닥에 빠르게 눕습니다 → 약 1.5초 뒤 "쓰러짐 감지" (주황)
3. 그대로 움직이지 않고 10초 → "무반응" 긴급 경보 + 119 카운트다운
4. 다시 일어나면 정상으로 돌아오는지 확인

## 3. 유선 IP 카메라 연결
1. 카메라(PoE)와 맥북을 같은 공유기/PoE 스위치에 연결 (맥북은 랜선 또는 같은 와이파이)
2. 카메라 설명서나 관리 앱에서 **RTSP 주소** 확인
   - 예: `rtsp://admin:비밀번호@192.168.0.10:554/stream1`
   - 화질은 **서브 스트림(저해상도)** 을 쓰는 게 AI 분석이 빠릅니다.
3. `config.yaml` 의 카메라 `source` 에 주소 입력 후 서버 다시 실행

## 카메라 대수 기준 (예상치)
| 카메라 | 설정 |
|---|---|
| 1~4대 | 기본값 (`fps: 5`) |
| 5~9대 | `fps: 3` 으로 낮추기 |
| 10대 이상 | 실제로 돌려보고 화면이 밀리면 `fps: 2`, 또는 장비 추가 검토 |

## 문제가 생기면
| 증상 | 해결 |
|---|---|
| 영상이 검은 화면 | 카메라 권한 확인, 다른 앱(줌·페이스타임)이 카메라를 쓰고 있지 않은지 확인 |
| `영상 열기 실패` 로그 | RTSP 주소·비밀번호 확인, 맥북과 카메라가 같은 네트워크인지 확인 |
| 느림 | `fps` 낮추기, 카메라 서브 스트림 사용 |
| mps 관련 오류 | `config.yaml` 에서 `device: cpu` 로 바꿔 실행 (느리지만 동작) |
