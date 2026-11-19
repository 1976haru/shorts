# ShortsMaker CLI 계약 (shorts_cli.py, `shorts_job.v1` / `shorts_batch.v1`)

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

### 4. batch
```
python shorts_cli.py batch --job <batch.json> [--no-stdin-cancel]
```
곡 폴더의 곡마다 숏츠 1개를 **순서대로 1개씩**(FFmpeg 동시 1개) 만듭니다.
마지막 줄은 `batch_result` 또는(작업 자체가 잘못된 경우) `error`입니다. 아래 "일괄 제작" 절 참고.

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

## 일괄 제작 (batch, `shorts_batch.v1`)

### 스키마

| 키 | 필수 | 형식 / 범위 | 기본값 | 설명 |
|---|---|---|---|---|
| `schema` | ✅ | `"shorts_batch.v1"` | — | |
| `audio_dir` | ✅¹ | 폴더 경로 | — | 음원 폴더(하위 폴더는 보지 않음). 음원 확장자 파일만 사용 |
| `audio_files` | ✅¹ | 경로 목록 | — | 직접 지정. 적은 순서대로 처리 |
| `background_dir` | ✅² | 폴더 경로 | — | 배경 영상 폴더(`.mp4 .mov .m4v .mkv .webm`만) |
| `background_files` | ✅² | 경로 목록 | — | 직접 지정 |
| `output_dir` | ✅ | 폴더 경로 | — | 없으면 만듭니다 |
| `duration` `start` `highlight_rank` `fit_mode` `fade_sec` `use_nvenc` | | | | `shorts_job.v1`과 같은 의미·기본값·검증 (`start` 기본 `"auto"`, `fit_mode` 기본 `"blur"`) |
| `assign` |  | `"rotate"` \| `"random"` | `"rotate"` | 배경 배정 방식 |
| `seed` |  | 정수 \| `null` | `null` | `random` 배정과 `video_offset:"random"`의 재현용. `null`이면 시간 기반(실제 값은 `batch_start.seed`) |
| `video_offset` |  | `"random"` \| 숫자 ≥ 0 | `"random"` | `"random"`: 곡마다 0 ~ (배경 길이 − 1초)에서 고름 |
| `name_template` |  | 문자열 | `"{stem}_short"` | `{stem}` 곡 파일명(확장자 제외), `{index}` 01부터 2자리, `{bg}` 배경 파일명(확장자 제외). 결과에 `.mp4`를 붙임 |
| `skip_existing` |  | `true` \| `false` | `true` | 같은 이름 출력이 있으면 건너뜀. `false`면 `_1`, `_2` …를 붙여 새로 만듦 |

¹ `audio_dir`와 `audio_files` 중 **정확히 하나**. ² `background_dir`와 `background_files` 중 **정확히 하나**. 둘 다 있거나 둘 다 없으면 `invalid_job`.

```json
{
  "schema": "shorts_batch.v1",
  "audio_dir": "D:/suno/1228",
  "background_dir": "D:/bg",
  "output_dir": "D:/out/1228_shorts",
  "duration": 45, "start": "auto", "highlight_rank": 1, "fit_mode": "blur", "fade_sec": 0.5, "use_nvenc": false,
  "assign": "random", "seed": null, "video_offset": "random",
  "name_template": "{index}_{stem}_short", "skip_existing": true
}
```

- 상대 경로는 batch.json 폴더 기준. 모르는 키는 `batch_result.warnings`에 `"unknown_key:<이름>"`.
- 폴더 스캔은 **자연 정렬**합니다(`2 - a.wav`가 `10 - b.wav`보다 앞). 대상 파일이 0개면 `invalid_job`, 폴더가 없으면 `input_not_found`.
- 배정
  - `rotate`: 정렬된 배경을 순서대로 반복(곡1=배경1, 곡2=배경2, …, 배경 수를 넘으면 처음부터).
  - `random`: 배경 목록을 seed로 섞은 묶음을 이어 붙입니다. 배경이 2개 이상이면 **같은 배경이 연속으로 나오지 않고**, 각 배경이 고르게 쓰입니다.
- 파일명: `name_template` 결과에서 Windows 금지 문자(`< > : " / \ | ? *`, 제어 문자)를 지우고, 끝의 점·공백을 없애며, `CON`·`NUL` 같은 예약 이름은 앞에 `_`를 붙입니다.
  여러 곡의 결과 이름이 같아지면(예: `{stem}` 없이 고정 이름) 렌더 전에 `invalid_job`.
- 시작 전 검사: 배경 영상은 모두 미리 검사합니다(손상된 배경 → `invalid_job`, 소리 있는 배경 → `warnings`에 `"background_audio_ignored:<파일명>"`).
  곡별 검사(길이, 하이라이트 범위, 손상 파일)는 그 곡 차례에 하며, 실패해도 다음 곡을 계속합니다.

### 이벤트

```json
{"event":"batch_start","total":15,"output_dir":"D:\\out\\1228_shorts","assign":"random","seed":1234,"csv":"D:\\out\\1228_shorts\\shorts_batch_20261119_210959.csv"}
{"event":"item_start","index":1,"total":15,"audio":"D:\\suno\\1228\\01 - a.wav","background":"D:\\bg\\lake.mp4","video_offset":12.345}
{"event":"progress","index":1,"value":0.42,"overall":0.028}
{"event":"item_result","index":1,"ok":true,"output":"D:\\out\\1228_shorts\\01 - a_short.mp4","start":82.0,"elapsed_sec":38.1,"warnings":[]}
{"event":"item_start","index":2,"total":15,"audio":"...","background":"...","video_offset":3.21}
{"event":"item_result","index":2,"ok":false,"code":"invalid_job","message":"음원에 오디오 스트림이 없습니다: 02 - b.wav"}
{"event":"item_start","index":3,"total":15,"audio":"...","background":"...","video_offset":7.5}
{"event":"item_result","index":3,"ok":true,"skipped":true,"output":"D:\\out\\1228_shorts\\03 - c_short.mp4"}
{"event":"batch_result","ok":false,"done":13,"failed":1,"skipped":1,"csv":"D:\\out\\1228_shorts\\shorts_batch_20261119_210959.csv","elapsed_sec":602.4,"warnings":[]}
```

- `batch_start`는 시작 전 검사를 모두 통과한 뒤 1회. `seed`는 실제로 사용한 값, `csv`는 로그 경로.
- `item_start`는 건너뛰는 곡을 포함해 모든 곡에 1회씩 나오고, 그 뒤에 그 곡의 `item_result`가 나옵니다.
- `progress`: `value`는 현재 곡의 진행률, `overall`은 전체 진행률(건너뛴·실패한 곡은 끝난 것으로 셈). 둘 다 단조 증가하며 `value`가 0.02 이상 커졌을 때만 나옵니다.
- 곡 실패의 `code`는 단일 render와 같은 값입니다: `invalid_job`(손상된 음원 등), `input_not_found`, `audio_too_short`, `highlight_out_of_range`, `render_failed`, `internal_error`.
- `batch_result.ok`는 실패 0개이고 취소되지 않았을 때 `true`. `done` = 새로 만든 개수, `skipped` = 건너뛴 개수.
- 취소되면 `batch_result`에 `"cancelled":true, "cancelled_remaining":<n>, "code":"cancelled"`가 붙습니다.
  `cancelled_remaining`은 **렌더 중이던 곡 + 시작하지 않은 곡**의 개수이며, 이 곡들은 `item_result`가 나오지 않습니다.
- 시작 전 검사에서 실패하면(작업 오류, 폴더 없음) `batch_start` 없이 `error` 한 줄만 나옵니다.

### 취소
- 단일 render와 같습니다: stdin `cancel` 한 줄 또는 stdin EOF.
- 진행 중인 곡의 FFmpeg를 멈추고 그 곡의 `*.part.mp4`를 지운 뒤 즉시 끝납니다. **이미 완성된 숏츠는 그대로 남습니다.**
- 같은 batch.json을 다시 실행하면(`skip_existing:true`) 완성된 곡은 건너뛰고 나머지만 이어서 만듭니다.
  (`seed:null`이면 다시 실행할 때 배정이 달라질 수 있으므로, 이어 만들기가 필요하면 `batch_start.seed` 값을 job에 적어 두세요.)

### CSV 로그
- `output_dir/shorts_batch_YYYYMMDD_HHMMSS.csv` (같은 초에 또 실행하면 `_1`…), UTF-8 BOM(엑셀에서 한글이 깨지지 않음).
- 열: `index, audio, background, video_offset, start, duration, fit_mode, status, output, code, message, elapsed_sec`
- `status`: `ok` | `failed` | `skipped` | `cancelled`(렌더 중 취소된 곡). 시작하지 않은 곡은 행이 없습니다.
- 곡이 끝날 때마다 한 줄씩 바로 기록하고 디스크에 flush합니다(중간에 프로세스가 죽어도 끝난 곡까지 남음).

## 종료 코드

| exit | `code` | 의미 | 재시도 |
|---|---|---|---|
| 0 | — | 성공 (`result`). batch는 모든 곡 성공 또는 건너뜀 | — |
| 2 | `invalid_job` | 작업 JSON 형식·값 오류, 잘못된 명령줄 인자, 손상된 입력 | 작업 수정 필요 |
| 2 | `highlight_out_of_range` | 숫자 `start` 구간이 곡 길이를 넘음 | 작업 수정 필요 |
| 2 | `audio_too_short` | 곡 길이가 duration보다 짧음 | 작업 수정 필요 |
| 3 | `input_not_found` | 작업·음원·배경·자막 파일 없음, batch의 폴더 없음 | 파일 확인 |
| 4 | `render_failed` | FFmpeg 실패 또는 SNS 호환 검증 실패 | 가능 |
| 5 | `cancelled` | stdin `cancel` / stdin EOF / Ctrl+C | — |
| 6 | — (batch 전용) | 일부 곡 실패. `batch_result.failed` ≥ 1, 나머지 곡은 완성됨 | 같은 batch.json 재실행 시 실패한 곡만 다시 시도 (`skip_existing`) |
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
.venv\Scripts\python.exe shorts_cli.py batch --job "D:\jobs\1228_batch.json"
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
