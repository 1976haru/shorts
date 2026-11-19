# ShortsMaker CLI 계약 (shorts_cli.py, job schema `shorts_job.v1`)

이 문서는 영상늘리기(github.com/1976haru/long)와 ShortsMaker 사이의 **유일한 연결 계약**입니다.
영상늘리기는 ShortsMaker 코드를 import하지 않고, 아래 CLI를 별도 프로세스로 실행합니다.

```
영상늘리기 ─ 숏츠 탭 ─► shorts_cli.py (별도 프로세스) ─► shorts_core.py ─► FFmpeg
              ▲ stdin: "cancel\n"          │ stdout: JSON Lines
              └────────────────────────────┘
```

## 출력 규칙 (모든 명령 공통)
- stdout에는 **JSON Lines만** 나옵니다: 한 줄에 JSON 객체 하나, 줄 끝은 `\n`.
- 모든 바이트는 ASCII(0x00~0x7F)입니다. 한글은 `\uXXXX`로 이스케이프됩니다(`json.loads`로 그대로 복원됨).
- 매 줄마다 flush됩니다. 경고·로그·디버그 출력은 모두 stderr로 갑니다(stderr는 계약이 아닙니다).
- 마지막 줄은 항상 결과(`version` / `highlights` / `result`) 또는 `error`입니다.

## 명령

### 1. version
```
python shorts_cli.py version
```
```json
{"event":"version","engine":"shorts","version":"0.7.1","job_schema":"shorts_job.v1"}
```
exit 0. `version`은 `VERSION.txt`에서 읽습니다.

### 2. analyze
```
python shorts_cli.py analyze --audio <path> [--duration 45]
```
```json
{"event":"highlights","audio":"D:\\music\\01_song.wav","audio_duration":213.28,
 "items":[{"rank":1,"start":82.0,"end":127.0,"duration":45.0,"score":0.41,"reason":"TOP 1"}, ...]}
```
- `items`는 1~3개, `rank` 오름차순. 모든 항목에서 `start + duration ≤ audio_duration`.
- `render`의 `"start":"auto"`가 고르는 값과 같습니다(`highlight_rank` = `rank`).
- `--duration`은 15~60. 곡이 duration보다 짧으면 `audio_too_short`.

### 3. render
```
python shorts_cli.py render --job <job.json> [--no-stdin-cancel]
```
진행 이벤트들을 출력하고, 마지막 줄에 `result` 또는 `error`를 출력합니다.

## 작업 JSON 스키마 `shorts_job.v1`

| 키 | 필수 | 형식 / 범위 | 기본값 | 설명 |
|---|---|---|---|---|
| `schema` | ✅ | `"shorts_job.v1"` | — | 값이 다르거나 없으면 `invalid_job` |
| `audio` | ✅ | 경로 | — | 음원 (wav, mp3, m4a, flac …) |
| `background` | ✅ | 경로, `.mp4 .mov .m4v .mkv .webm` | — | 소리 없는 루프 배경 영상. 오디오가 있어도 출력에 섞이지 않음 |
| `output` | ✅ | 경로, `.mp4` | — | 이미 있으면 `_1`, `_2` … 를 붙여 저장 (덮어쓰지 않음) |
| `duration` |  | 숫자 15~60 | `45` | 숏츠 길이(초) |
| `start` |  | `"auto"` 또는 숫자 ≥ 0 | `"auto"` | 음원 시작 위치(초) |
| `highlight_rank` |  | 정수 1~3 | `1` | `start`가 `"auto"`일 때 사용할 후보 순위 |
| `fit_mode` |  | `"crop"` \| `"blur"` | `"blur"` | crop: 꽉 채워 자르기, blur: 흐린 배경 위에 원본 비율 유지 |
| `video_offset` |  | 숫자 ≥ 0 | `0` | 배경 영상 시작 위치(초) |
| `fade_sec` |  | 숫자 ≥ 0 | `0.5` | 영상·오디오 fade in/out (최대 duration/4) |
| `subtitle` |  | `.srt` 경로 또는 `""` | `""` | 지정했는데 파일이 없으면 `input_not_found` |
| `use_nvenc` |  | `true` \| `false` | `false` | NVENC가 없으면 자동으로 libx264 사용 |

```json
{
  "schema": "shorts_job.v1",
  "audio": "D:/music/01_song.wav",
  "background": "D:/bg/lake.mp4",
  "output": "D:/out/01_song_short.mp4",
  "duration": 45,
  "start": "auto",
  "highlight_rank": 1,
  "fit_mode": "blur",
  "video_offset": 0,
  "fade_sec": 0.5,
  "subtitle": "",
  "use_nvenc": false
}
```

- 파일은 UTF-8(BOM 허용) JSON 객체여야 합니다.
- **상대 경로는 job.json 파일이 있는 폴더 기준**으로 해석합니다(CLI를 실행한 폴더가 아님).
- **모르는 키는 거부하지 않습니다.** `result.warnings`에 `"unknown_key:<이름>"`으로 기록됩니다.
  그래서 영상늘리기가 더 새로운 키를 보내도 이전 엔진이 계속 동작합니다.

## 사전 검사 (렌더 전, 수 초 이내)
1. 작업 JSON 형식·범위 검사 → `invalid_job`
2. 음원·배경·자막 파일 존재 → `input_not_found`
3. 음원 길이 측정(ffprobe). 곡 길이 < duration → `audio_too_short`
4. `start`가 숫자: `start + duration > 곡 길이 + 0.05` → `highlight_out_of_range`
   (예: `"선택 구간(30.0~50.0초)이 곡 길이(40.0초)를 넘습니다."`)
5. `start`가 `"auto"`: 하이라이트 분석(librosa) 후 `highlight_rank` 후보 사용.
   해당 순위가 없으면 1위를 쓰고 `warnings`에 `"highlight_rank_unavailable:<요청>->1"`.
   후보가 곡 끝을 넘으면 `start = max(0, 곡 길이 - duration)`으로 당깁니다.
   분석은 곡 길이에 따라 수 초가 더 걸릴 수 있습니다.
6. 배경 영상 검사: 영상 스트림이 없거나 1초 미만 → `invalid_job`.
   배경에 오디오가 있으면 `warnings`에 `"background_audio_ignored"`.

## 이벤트 형식 (render)

```json
{"event":"start","job":"D:\\jobs\\01.json","audio":"D:\\music\\01_song.wav","background":"D:\\bg\\lake.mp4","start":82.0,"duration":45.0}
{"event":"progress","value":0.0}
{"event":"progress","value":0.0517}
...
{"event":"progress","value":1.0}
{"event":"result","ok":true,"output":"D:\\out\\01_song_short.mp4","duration":45.021,"start":82.0,"fit_mode":"blur","background_had_audio":false,"warnings":[],"elapsed_sec":38.4}
```

- `start`: 사전 검사를 통과하고 렌더 직전에 1회. `start`는 실제로 결정된 음원 시작(초).
- `progress`: `value`는 0.0~1.0, 단조 증가. 직전 출력보다 0.02 이상 커졌을 때만 출력하며, 성공 시 마지막은 `1.0`.
- `result`: 성공. `output`은 실제 저장 경로(번호가 붙었을 수 있음). `duration`은 실측 길이.
  출력 파일은 SNS 호환 검증(H.264 High 4.1, 1080x1920, 30fps CFR, yuv420p BT.709, AAC-LC 48kHz stereo, faststart)을 통과한 것입니다.
- 사전 검사에서 실패하면 `start` 없이 `error` 한 줄만 나옵니다.

```json
{"event":"error","ok":false,"code":"highlight_out_of_range","message":"선택 구간(30.0~50.0초)이 곡 길이(40.0초)를 넘습니다."}
```

## 종료 코드

| exit | `code` | 의미 | 재시도 |
|---|---|---|---|
| 0 | — | 성공 (`result`) | — |
| 2 | `invalid_job` | 작업 JSON 형식·값 오류, 잘못된 명령줄 인자, 손상된 입력 | 작업 수정 필요 |
| 2 | `highlight_out_of_range` | 숫자 `start` 구간이 곡 길이를 넘음 | 작업 수정 필요 |
| 2 | `audio_too_short` | 곡 길이가 duration보다 짧음 | 작업 수정 필요 |
| 3 | `input_not_found` | 작업·음원·배경·자막 파일 없음 | 파일 확인 |
| 4 | `render_failed` | FFmpeg 실패 또는 SNS 호환 검증 실패 | 가능 |
| 5 | `cancelled` | stdin `cancel` / stdin EOF / Ctrl+C | — |
| 1 | `internal_error` | 그 밖의 예외 (예: 분석에 필요한 librosa 없음) | 로그(stderr) 확인 |

## 취소
- **stdin으로 `cancel` 한 줄**을 보내면 취소합니다(대소문자 무시, 앞뒤 공백 무시).
- **stdin이 EOF**가 되면(부모가 파이프를 닫았거나 부모 프로세스가 죽음) 역시 취소합니다.
  따라서 stdin을 `DEVNULL`/`NUL`로 주면 즉시 `cancelled`로 끝납니다.
- `--no-stdin-cancel`: stdin을 감시하지 않습니다. 터미널에서 사람이 직접 실행할 때 사용합니다.
  (Windows 콘솔에서 직접 실행하면 stdin은 감시하지 않으며 Ctrl+C로 취소합니다.)
- 취소되면 FFmpeg를 종료하고 임시 파일(`*.part.mp4`)을 지운 뒤 `cancelled` / exit 5로 끝납니다.
  출력 파일은 만들어지지 않습니다. 실측: 취소 신호 후 1초 이내 종료.

## Windows 호출 예

```bat
cd /d D:\03_shorts
.venv\Scripts\python.exe shorts_cli.py version
.venv\Scripts\python.exe shorts_cli.py analyze --audio "D:\music\01_song.wav" --duration 45
.venv\Scripts\python.exe shorts_cli.py render --job "D:\jobs\01_song.json"
```

Python 호출 측 예 (영상늘리기):

```python
import json, subprocess

proc = subprocess.Popen(
    [r"D:\03_shorts\.venv\Scripts\python.exe", r"D:\03_shorts\shorts_cli.py", "render", "--job", job_path],
    cwd=r"D:\03_shorts",
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    creationflags=subprocess.CREATE_NO_WINDOW,
)
# stderr는 별도 스레드에서 계속 읽어 버릴 것 (파이프 막힘 방지)
for raw in proc.stdout:                 # 한 줄씩
    event = json.loads(raw.decode("ascii"))
    if event["event"] == "progress":
        update_bar(event["value"])
    elif event["event"] in ("result", "error"):
        final = event
code = proc.wait()
proc.stdin.close()

# 취소할 때:
#   proc.stdin.write(b"cancel\n"); proc.stdin.flush()
#   proc.wait(timeout=10)  → 시간 초과 시에만 proc.kill()
```

## 호출하는 쪽(영상늘리기)이 지켜야 할 점
1. **stdout을 한 줄씩 읽어** JSON으로 파싱합니다. 마지막 `result`/`error` 줄과 exit 코드로 성공을 판단합니다.
2. **stdin 파이프를 열어 둡니다**(`stdin=PIPE`). 렌더가 끝날 때까지 닫지 않습니다. 닫으면 취소로 처리됩니다.
3. **취소는 `"cancel\n"`을 보낸 뒤 최대 10초 기다립니다.** 그래도 끝나지 않을 때만 프로세스를 강제 종료합니다
   (강제 종료하면 `*.part.mp4`가 남을 수 있습니다).
4. stderr는 별도 스레드에서 계속 비웁니다(읽지 않으면 버퍼가 차서 멈출 수 있음). 내용은 로그용이며 계약이 아닙니다.
5. Windows에서는 `creationflags=CREATE_NO_WINDOW`로 실행합니다. CLI 내부의 FFmpeg/ffprobe도 창 없이 실행됩니다.
6. `cwd`는 ShortsMaker 폴더로 두는 것을 권장합니다(job 안의 상대 경로는 cwd와 무관하게 job 파일 기준).
7. 모르는 `code`나 새 이벤트가 오면 무시하거나 일반 오류로 처리합니다. 필드는 앞으로 추가될 수 있지만 삭제·의미 변경은 job schema 버전을 올려서 합니다.
8. ShortsMaker 저장소의 파이썬 코드를 import하거나 복사하지 않습니다.
