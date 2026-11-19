# ShortsMaker Studio Roadmap

## 구조

```
영상늘리기(화면 하나) ─ 숏츠 탭 ─► shorts_cli.py(별도 프로세스) ─► shorts_core.py ─► FFmpeg
```

- 영상늘리기(github.com/1976haru/long)와 ShortsMaker의 코드는 합치지 않는다.
- 연결은 CLI 호출 + JSON 파일 계약으로만 한다.
- ShortsMaker의 `app.py`(Tkinter 화면)는 단독 실행용으로 계속 유지한다.

## 단계

- [x] #1 v0.6.1 기반 정리 + 엔진 분리 원칙 고정 — 완료 기준: 버전 단일화, CLAUDE.md/AGENTS.md 규칙과 `tests/test_baseline.py` 통과
- [ ] #2 엔진: 소리 없는 루프 배경 영상 + 음원 하이라이트 → 9:16 숏츠 렌더 함수 (v0.7.0) — 완료 기준: 새 함수가 `social_*` 파이프라인으로 렌더하고 `validate_social_video`를 통과, 기존 이미지 모드 테스트 무변경 통과
- [ ] #3 엔진: 화면 없는 CLI `shorts_cli.py` — 작업 JSON 입력, 진행률/결과 JSON 출력 — 완료 기준: tkinter 없이 CLI 한 번 호출로 숏츠 1개 생성, 진행률/결과 JSON 스키마 테스트 통과
- [ ] #4 영상늘리기(long) 저장소에 "숏츠" 탭 추가 — #3 CLI를 별도 프로세스로 호출 (long 저장소 작업) — 완료 기준: long 화면에서 숏츠 제작 성공, 두 저장소 간 코드 import 0
- [ ] #5 일괄 제작: 음원 폴더 × 배경 영상 풀 순환 배정 — 완료 기준: N개 음원을 배경 영상 풀에 순환 배정해 N개 숏츠 생성, 원본 덮어쓰기 0
- [ ] #6 Suno Studio 연동: `inbox/` 폴더의 `song.v1` JSON 읽기 — 완료 기준: `song.v1` 샘플 JSON으로 제작 작업이 생성되고 잘못된 JSON은 명확한 오류로 거부
- [ ] #7 결과 출력: `outbox/` 폴더에 `shorts.v1` JSON → 영상늘리기 예약·업로드가 읽음 — 완료 기준: 렌더 결과마다 `shorts.v1` JSON 생성, long 쪽에서 읽어 예약 목록에 표시
- [ ] #8 Windows 실측 검증 + 릴리스 — 완료 기준: 깨끗한 Windows 10/11에서 INSTALL → START → 제작 → 업로드 호환 검증 통과 후 태그 릴리스
