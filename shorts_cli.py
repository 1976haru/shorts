"""ShortsMaker headless CLI (contract: docs/CLI.md).

stdout carries JSON Lines only (one ASCII JSON object per line).
Anything else -- stray prints, warnings, logs -- goes to stderr.
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

# Keep the real stdout for events; route every other write to stderr.
_EVENT_OUT = sys.stdout.buffer
sys.stdout = sys.stderr

import shorts_core as core  # noqa: E402

JOB_SCHEMA = "shorts_job.v1"
ENGINE_NAME = "shorts"
DEFAULT_DURATION = 45.0
PROGRESS_STEP = 0.02
OUT_OF_RANGE_TOLERANCE = 0.05

EXIT_CODES = {
    "invalid_job": 2,
    "highlight_out_of_range": 2,
    "audio_too_short": 2,
    "input_not_found": 3,
    "render_failed": 4,
    "cancelled": 5,
    "internal_error": 1,
}

JOB_KEYS = {
    "schema",
    "audio",
    "background",
    "output",
    "duration",
    "start",
    "highlight_rank",
    "fit_mode",
    "video_offset",
    "fade_sec",
    "subtitle",
    "use_nvenc",
}


class CliError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def engine_version():
    try:
        first = (Path(__file__).with_name("VERSION.txt")).read_text(encoding="utf-8-sig").splitlines()[0]
    except (OSError, IndexError):
        return "unknown"
    match = re.search(r"v(\d+\.\d+\.\d+)", first)
    return match.group(1) if match else "unknown"


def emit(event, **fields):
    line = json.dumps({"event": event, **fields}, ensure_ascii=True, separators=(",", ":"))
    _EVENT_OUT.write(line.encode("ascii") + b"\n")
    _EVENT_OUT.flush()


# ------------------------------------------------------------------ job parsing

def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(job, key, default, low=None, high=None):
    value = job.get(key, default)
    if not _is_number(value):
        raise CliError("invalid_job", f"'{key}' 값은 숫자여야 합니다: {value!r}")
    value = float(value)
    if (low is not None and value < low) or (high is not None and value > high):
        bounds = f"{low:g} 이상" if high is None else f"{low:g}~{high:g}"
        raise CliError("invalid_job", f"'{key}' 값이 허용 범위({bounds})를 벗어났습니다: {value:g}")
    return value


def _path(job, key, base, required=True):
    value = job.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise CliError("invalid_job", f"'{key}' 값은 경로 문자열이어야 합니다.")
    if not value.strip():
        if required:
            raise CliError("invalid_job", f"필수 항목 '{key}'가 없습니다.")
        return None
    p = Path(value.strip())
    if not p.is_absolute():
        p = base / p
    return Path(os.path.abspath(p))


def load_job(job_path):
    job_file = Path(os.path.abspath(job_path))
    if not job_file.is_file():
        raise CliError("input_not_found", f"작업 파일이 없습니다: {job_file}")
    try:
        job = json.loads(job_file.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CliError("invalid_job", f"작업 파일을 JSON으로 읽을 수 없습니다: {exc}")
    if not isinstance(job, dict):
        raise CliError("invalid_job", "작업 파일의 최상위 값은 JSON 객체여야 합니다.")
    if job.get("schema") != JOB_SCHEMA:
        raise CliError("invalid_job", f"'schema' 값은 \"{JOB_SCHEMA}\"이어야 합니다: {job.get('schema')!r}")

    base = job_file.parent
    warnings_out = [f"unknown_key:{key}" for key in job if key not in JOB_KEYS]

    audio = _path(job, "audio", base)
    background = _path(job, "background", base)
    output = _path(job, "output", base)
    subtitle = _path(job, "subtitle", base, required=False)

    if background.suffix.lower() not in core.VIDEO_EXTS:
        allowed = ", ".join(sorted(core.VIDEO_EXTS))
        raise CliError("invalid_job", f"배경 영상 확장자는 {allowed} 중 하나여야 합니다: {background.name}")
    if output.suffix.lower() != ".mp4":
        raise CliError("invalid_job", f"출력 파일은 .mp4여야 합니다: {output.name}")
    if subtitle is not None and subtitle.suffix.lower() != ".srt":
        raise CliError("invalid_job", f"자막 파일은 .srt여야 합니다: {subtitle.name}")
    if os.path.normcase(str(output)) in {os.path.normcase(str(audio)), os.path.normcase(str(background))}:
        raise CliError("invalid_job", "출력 경로가 입력 파일과 같습니다. 원본을 덮어쓸 수 없습니다.")

    duration = _number(job, "duration", DEFAULT_DURATION, core.VIDEO_SHORT_MIN_DURATION, core.VIDEO_SHORT_MAX_DURATION)

    start = job.get("start", "auto")
    if start != "auto":
        start = _number(job, "start", None, 0.0)

    rank = job.get("highlight_rank", 1)
    if not (isinstance(rank, int) and not isinstance(rank, bool) and 1 <= rank <= 3):
        raise CliError("invalid_job", f"'highlight_rank' 값은 1~3 정수여야 합니다: {rank!r}")

    fit_mode = job.get("fit_mode", "blur")
    if fit_mode not in core.VIDEO_FIT_MODES:
        raise CliError("invalid_job", f"'fit_mode' 값은 crop 또는 blur여야 합니다: {fit_mode!r}")

    use_nvenc = job.get("use_nvenc", False)
    if not isinstance(use_nvenc, bool):
        raise CliError("invalid_job", f"'use_nvenc' 값은 true/false여야 합니다: {use_nvenc!r}")

    return {
        "job_file": job_file,
        "audio": audio,
        "background": background,
        "output": output,
        "subtitle": subtitle,
        "duration": duration,
        "start": start,
        "highlight_rank": rank,
        "fit_mode": fit_mode,
        "video_offset": _number(job, "video_offset", 0.0, 0.0),
        "fade_sec": _number(job, "fade_sec", 0.5, 0.0),
        "use_nvenc": use_nvenc,
        "warnings": warnings_out,
    }


# ------------------------------------------------------------ input checks

def _require_file(path, label):
    if not path.is_file():
        raise CliError("input_not_found", f"{label} 파일이 없습니다: {path}")


def _audio_duration(audio):
    _require_file(audio, "음원")
    try:
        return core.probe_audio_duration(audio)
    except ValueError as exc:
        raise CliError("invalid_job", str(exc))


def _check_length(total, duration):
    if total + OUT_OF_RANGE_TOLERANCE < duration:
        raise CliError("audio_too_short", f"곡 길이({total:.1f}초)가 숏츠 길이({duration:.1f}초)보다 짧습니다.")


def highlight_candidates(audio, duration, total):
    """Ranked highlight starts for a short of `duration` seconds, clamped to the song."""
    _check_length(total, duration)
    try:
        found = core.analyze_top_highlights(str(audio), target_duration=max(30.0, duration))
    except RuntimeError as exc:
        raise CliError("internal_error", f"하이라이트 분석을 할 수 없습니다: {exc}")
    items = []
    for rank, h in enumerate(found, 1):
        start = float(h.start)
        if start + duration > total:
            start = max(0.0, total - duration)
        start = round(start, 3)
        items.append(
            {
                "rank": rank,
                "start": start,
                "end": round(start + duration, 3),
                "duration": round(duration, 3),
                "score": float(h.score),
                "reason": h.reason,
            }
        )
    return items


def resolve_start(job, total, warnings_out):
    duration = job["duration"]
    _check_length(total, duration)
    if job["start"] != "auto":
        start = job["start"]
        if start + duration > total + OUT_OF_RANGE_TOLERANCE:
            raise CliError(
                "highlight_out_of_range",
                f"선택 구간({start:.1f}~{start + duration:.1f}초)이 곡 길이({total:.1f}초)를 넘습니다.",
            )
        return round(start, 3)
    items = highlight_candidates(job["audio"], duration, total)
    if not items:
        raise CliError("internal_error", "하이라이트 후보를 찾지 못했습니다.")
    rank = job["highlight_rank"]
    if rank > len(items):
        warnings_out.append(f"highlight_rank_unavailable:{rank}->1")
        rank = 1
    return items[rank - 1]["start"]


# ------------------------------------------------------------ cancellation

STDIN_POLL_SEC = 0.1
_WIN_FILE_TYPE_CHAR = 0x0002
_WIN_FILE_TYPE_PIPE = 0x0003


def _windows_stdin_chunks(fd, cancel_event):
    """Yield stdin bytes on Windows without ever leaving a ReadFile pending.

    A blocking read on an anonymous pipe makes other threads hang when they
    touch the same handle (e.g. the CRT probing std handles while scipy's
    BLAS DLL loads during highlight analysis), so pipes are polled with
    PeekNamedPipe and only the bytes already available are read.
    Yields b"" once on EOF (writer closed the pipe or the parent died).
    """
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    kernel32.GetFileType.restype = wintypes.DWORD
    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetConsoleMode.restype = wintypes.BOOL

    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    file_type = kernel32.GetFileType(handle)
    mode = wintypes.DWORD(0)
    if file_type == _WIN_FILE_TYPE_CHAR and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return  # interactive console: not watched, Ctrl+C cancels instead
    if file_type != _WIN_FILE_TYPE_PIPE:
        while True:  # file or NUL redirect: reads never block, NUL is EOF at once
            chunk = os.read(fd, 4096)
            yield chunk
            if not chunk:
                return

    available = wintypes.DWORD(0)
    while not cancel_event.is_set():
        if not kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
            yield b""  # ERROR_BROKEN_PIPE (109) or any other failure means the pipe is gone
            return
        if available.value:
            yield os.read(fd, available.value)
        else:
            cancel_event.wait(STDIN_POLL_SEC)


def _posix_stdin_chunks(fd, cancel_event):
    while not cancel_event.is_set():
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            chunk = b""
        yield chunk
        if not chunk:
            return


def watch_stdin(cancel_event):
    """Set cancel_event on a 'cancel' line or on stdin EOF.

    Uses the raw file descriptor (never sys.stdin's buffer) so the watcher
    cannot hold the stdin buffer lock during interpreter shutdown.
    """

    def run():
        try:
            fd = sys.stdin.fileno()
        except (AttributeError, OSError, ValueError):
            cancel_event.set()  # no stdin at all: treat like a closed pipe
            return
        reader = _windows_stdin_chunks if os.name == "nt" else _posix_stdin_chunks
        buffer = b""
        try:
            for chunk in reader(fd, cancel_event):
                if not chunk:
                    cancel_event.set()
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip().lower() == b"cancel":
                        cancel_event.set()
                        return
        except OSError:
            cancel_event.set()

    thread = threading.Thread(target=run, name="stdin-cancel", daemon=True)
    thread.start()
    return thread


# ------------------------------------------------------------ commands

def cmd_version(_args):
    emit("version", engine=ENGINE_NAME, version=engine_version(), job_schema=JOB_SCHEMA)
    return 0


def cmd_analyze(args):
    audio = Path(os.path.abspath(args.audio))
    duration = float(args.duration)
    if not (core.VIDEO_SHORT_MIN_DURATION <= duration <= core.VIDEO_SHORT_MAX_DURATION):
        raise CliError("invalid_job", f"--duration 값은 15~60초여야 합니다: {duration:g}")
    total = _audio_duration(audio)
    emit("highlights", audio=str(audio), audio_duration=total, items=highlight_candidates(audio, duration, total))
    return 0


def cmd_render(args):
    started = time.perf_counter()
    cancel_event = threading.Event()
    if not args.no_stdin_cancel:
        watch_stdin(cancel_event)

    job = load_job(args.job)
    warnings_out = job["warnings"]
    _require_file(job["background"], "배경 영상")
    if job["subtitle"] is not None:
        _require_file(job["subtitle"], "자막")
    total = _audio_duration(job["audio"])

    try:
        background = core.probe_background_video(job["background"])
    except FileNotFoundError as exc:
        raise CliError("input_not_found", str(exc))
    except ValueError as exc:
        raise CliError("invalid_job", str(exc))
    if background["has_audio"]:
        warnings_out.append("background_audio_ignored")

    if cancel_event.is_set():
        raise CliError("cancelled", "렌더가 취소되었습니다.")
    start = resolve_start(job, total, warnings_out)
    duration = job["duration"]
    emit(
        "start",
        job=str(job["job_file"]),
        audio=str(job["audio"]),
        background=str(job["background"]),
        start=start,
        duration=duration,
    )

    last = [None]

    def on_progress(value):
        value = round(float(value), 4)
        previous = last[0]
        if previous is None or value - previous >= PROGRESS_STEP or (value >= 1.0 > previous):
            last[0] = value
            emit("progress", value=value)

    try:
        result = core.render_video_short(
            job["audio"],
            job["background"],
            job["output"],
            start,
            duration,
            fit_mode=job["fit_mode"],
            video_offset=job["video_offset"],
            fade_sec=job["fade_sec"],
            subtitle_path=str(job["subtitle"] or ""),
            use_nvenc=job["use_nvenc"],
            nvenc_available_fn=core.nvenc_available_no_window,
            progress_cb=on_progress,
            cancel_event=cancel_event,
        )
    except core.RenderCancelled:
        raise CliError("cancelled", "렌더가 취소되었습니다.")
    except FileNotFoundError as exc:
        raise CliError("input_not_found", str(exc))
    except ValueError as exc:
        raise CliError("invalid_job", str(exc))
    except RuntimeError as exc:
        raise CliError("render_failed", f"렌더에 실패했습니다: {exc}")

    emit(
        "result",
        ok=True,
        output=result["output"],
        duration=result["duration"],
        start=start,
        fit_mode=job["fit_mode"],
        background_had_audio=result["background_had_audio"],
        warnings=warnings_out,
        elapsed_sec=round(time.perf_counter() - started, 2),
    )
    return 0


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("invalid_job", f"명령줄 인자 오류: {message}")


def build_parser():
    parser = _Parser(prog="shorts_cli.py", description="ShortsMaker headless engine (JSON Lines on stdout).")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    sub.add_parser("version", help="print engine version")
    analyze = sub.add_parser("analyze", help="list TOP3 highlight candidates")
    analyze.add_argument("--audio", required=True)
    analyze.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    render = sub.add_parser("render", help="render one short from a shorts_job.v1 file")
    render.add_argument("--job", required=True)
    render.add_argument("--no-stdin-cancel", action="store_true", help="do not watch stdin for cancel/EOF")
    return parser


COMMANDS = {"version": cmd_version, "analyze": cmd_analyze, "render": cmd_render}


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        return COMMANDS[args.command](args)
    except CliError as exc:
        emit("error", ok=False, code=exc.code, message=exc.message)
        return EXIT_CODES[exc.code]
    except KeyboardInterrupt:  # Ctrl+C in a terminal; render_video_short already removed .part
        emit("error", ok=False, code="cancelled", message="사용자가 렌더를 중단했습니다.")
        return EXIT_CODES["cancelled"]
    except SystemExit as exc:  # argparse --help
        return int(exc.code or 0)
    except Exception as exc:
        emit("error", ok=False, code="internal_error", message=f"{type(exc).__name__}: {exc}")
        return EXIT_CODES["internal_error"]


if __name__ == "__main__":
    code = main()
    sys.stderr.flush()
    sys.exit(code)
