# AGENTS.md

ShortsMaker Studio 저장소에서 작업하는 AI 에이전트용 규칙입니다.
CLAUDE.md와 AGENTS.md의 핵심 규칙은 항상 동일하게 유지합니다. 한쪽을 고치면 다른 쪽도 같이 고칩니다.

## 구조 원칙
이 프로그램은 "엔진"과 "화면"으로 나뉩니다.
- 엔진 = `shorts_core.py` (+ 앞으로 추가될 `shorts_cli.py`). 다른 프로그램(영상늘리기, github.com/1976haru/long)이 별도 프로세스로 호출해 숏츠를 만듭니다.
- 화면 = `app.py` (Tkinter UI). 단독 실행도 계속 지원합니다.
- 두 저장소의 코드는 합치지 않습니다. 연결은 CLI 호출 + JSON 파일 계약으로만 합니다.

## 핵심 규칙
1. 엔진(`shorts_core.py`, 이후 `shorts_cli.py`)은 `tkinter`, `tkinterdnd2`, `pygame`을 import하지 않는다. 화면 없이 다른 프로세스에서 호출될 수 있어야 한다.
2. 엔진 함수는 진행률·로그를 `print`나 UI 직접 호출이 아니라 콜백/반환값으로 전달한다. (기존 함수는 그대로 두고, 새 함수부터 적용)
3. 기존 이미지 배경 모드를 회귀시키지 않는다. `build_render_short_command`의 출력은 바꾸지 않고, 새 기능은 새 함수로 추가한다.
4. SNS 호환 파이프라인(BT.709, yuv420p, 30fps CFR, AAC-LC 48kHz stereo, faststart)은 모든 렌더 경로에서 `social_*` 공통 함수를 재사용한다.
5. GUI 스레드에서 FFmpeg나 librosa를 실행하지 않는다.
6. 원본 음원·이미지·영상을 덮어쓰지 않는다. 출력 이름이 겹치면 번호를 붙인다.
7. 영상늘리기(long) 저장소의 코드를 복사해 오거나 import하지 않는다. 연결은 CLI + JSON 계약으로만 한다.
8. 새 Python 의존성은 명확한 이점이 있을 때만 추가하고, `requirements.txt`에 이유를 주석으로 남긴다.
9. `.bat` 파일은 내용과 파일명 모두 영문 ASCII만 사용한다.
10. 버전은 `VERSION.txt`(1행)가 기준이며 `app.py`의 `APP_VERSION`과 항상 일치해야 한다.
11. 변경 후 필수 검증:
    - `python -m pytest -q`
    - `python -m compileall -q .`
    - `git diff --check`

## 중요 파일 지도
- `shorts_core.py` — 분석·렌더·검증 엔진
- `app.py` — Tkinter 화면
- `tests/` — 회귀 테스트 (`test_baseline.py`가 위 규칙 1, 9, 10을 자동 검사)
- `VERSION.txt` — 버전 단일 기준
- `docs/ROADMAP.md` — 단계별 계획
