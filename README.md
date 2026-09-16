# ShortsMaker Studio v0.5.2

ShortsMaker Studio는 음원과 이미지를 9:16 숏츠 영상으로 제작하는 Windows용 도구입니다.

### v0.5.2

* TikTok upload compatibility fix
* BT.709 color pipeline
* yuv420p / limited range
* CFR 30fps
* AAC-LC 48kHz stereo
* post-render compatibility validation
* SNS compatibility converter
* batch compatibility converter

## v0.6 핵심 기능
- 밝은 작업형 Light UI
- 애니메이션 `끔` 옵션
- 감성형 랜덤, 줌인/줌아웃, 팬, 대각선, 후렴 강조형 Motion Engine
- 하단 안전영역 자막 기본값
- 자막 위치/크기/스타일 프리셋
- 음원 2개 + 이미지 2개를 한 번에 처리하는 `2개 동시 제작`
- A/B 세트별 TOP3 분석, 미리보기, 상태/로그 분리
- 선택 옵션 기반 썸네일 추출 및 듀얼 결과 ZIP 패키지
- 기존 단일 제작, 일괄 제작, 업로드 준비, NVENC, SRT, TOP3 분석 유지

## 기본 흐름
1. `실행.bat` 또는 `START.bat` 실행
2. `단일 제작` 또는 `2개 동시 제작` 선택
3. 음원, 이미지, 선택 SRT 지정
4. TOP3 분석 후 후보 선택
5. 공통 영상/모션/자막 설정 확인
6. 렌더 실행

## 자세한 v0.6 문서
`docs/shortsmaker-v0.6.md`를 참고하세요.
