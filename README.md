# ShortsMaker Studio v0.7.1

ShortsMaker Studio는 음원과 이미지를 9:16 숏츠 영상으로 제작하는 Windows용 도구입니다.

## v0.7.1 화면 없는 실행 (CLI)
- `.venv\Scripts\python.exe shorts_cli.py version` — 엔진 버전 확인
- `.venv\Scripts\python.exe shorts_cli.py analyze --audio 곡.wav --duration 45` — TOP3 하이라이트 후보
- `.venv\Scripts\python.exe shorts_cli.py render --job job.json` — 작업 JSON(`shorts_job.v1`)으로 숏츠 1개 제작, 진행률/결과를 JSON Lines로 출력

입력 스키마, 이벤트, 종료 코드, 취소 방법은 [docs/CLI.md](docs/CLI.md)를 참고하세요.

## v0.7.0 엔진: 영상 배경 렌더(UI 연결은 다음 단계)
- `shorts_core.render_video_short`: 소리 없는 루프 배경 영상(16:9 또는 9:16 MP4) + 음원 하이라이트 → 9:16 숏츠 (`crop` / `blur` 맞춤)
- 배경 영상의 오디오는 출력에 섞이지 않으며, 진행률 콜백·취소·SNS 호환 자동 검증을 지원합니다.
- 화면(app.py)에서는 아직 사용할 수 없습니다.

## v0.6.1 — 현재 기능
- SNS 호환 영상 파이프라인: BT.709 색공간, yuv420p / limited range, CFR 30fps, AAC-LC 48kHz stereo, faststart
- TikTok / YouTube Shorts 업로드 호환성 보정
- 렌더 후 호환성 자동 검증
- SNS 호환 변환기 및 폴더 일괄 변환기
- 밝은 작업형 Light UI
- 애니메이션 `끔` 옵션
- 감성형 랜덤, 줌인/줌아웃, 팬, 대각선, 후렴 강조형 Motion Engine
- 하단 안전영역 자막 기본값
- 자막 위치/크기/스타일 프리셋
- 음원 2개 + 이미지 2개를 한 번에 처리하는 `2개 동시 제작`
- A/B 세트별 TOP3 분석, 미리보기, 상태/로그 분리
- 선택 옵션 기반 썸네일 추출 및 듀얼 결과 ZIP 패키지
- 단일 제작, 일괄 제작, 업로드 준비, NVENC, SRT, TOP3 분석

## 설치 및 실행
1. `INSTALL.bat` 실행 (최초 1회)
2. `START.bat` 실행
3. 설치 문제는 `TROUBLESHOOTING_KO.txt` 참고 (`.venv`가 깨졌다면 `REPAIR.bat` 후 재설치)

## 기본 흐름
1. `START.bat` 실행
2. `단일 제작` 또는 `2개 동시 제작` 선택
3. 음원, 이미지, 선택 SRT 지정
4. TOP3 분석 후 후보 선택
5. 공통 영상/모션/자막 설정 확인
6. 렌더 실행

## 구조
- `shorts_core.py` — 분석·렌더·검증 엔진 (화면 없음, 다른 프로세스에서 호출 가능)
- `app.py` — Tkinter 화면
- `tests/` — 회귀 테스트

개발 규칙은 `CLAUDE.md` / `AGENTS.md`, 향후 계획은 `docs/ROADMAP.md`를 참고하세요.

## 자세한 v0.6 문서
`docs/shortsmaker-v0.6.md`를 참고하세요.
