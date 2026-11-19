"""shorts_cli.py contract tests -- every test runs the real CLI in a subprocess.

Set SHORTS_CLI_REPORT=<path.json> to dump timings and the auto-start result.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import shorts_core

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "shorts_cli.py"
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
HAS_FFMPEG = bool(shorts_core.ffprobe_path()) and (
    Path(shorts_core.ffmpeg_path()).exists() or shutil.which(shorts_core.ffmpeg_path())
)
REPORT = {}


class CliRun:
    def __init__(self, code, lines, raw, stderr, elapsed):
        self.code = code
        self.lines = lines
        self.raw = raw
        self.stderr = stderr
        self.elapsed = elapsed

    @property
    def last(self):
        return self.lines[-1]

    def events(self, name):
        return [line for line in self.lines if line.get("event") == name]


def run_cli(*args, on_line=None, timeout=300, stdin=subprocess.PIPE):
    """Run the CLI like a real caller: stdin pipe kept open, stdout read line by line.

    on_line(event, proc) may write to or close proc.stdin.
    """
    started = time.perf_counter()
    proc = subprocess.Popen(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=ROOT,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **NO_WINDOW,
    )
    stderr_chunks = []
    drain = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
    drain.start()
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    raw = b""
    lines = []
    try:
        for chunk in iter(proc.stdout.readline, b""):
            raw += chunk
            event = json.loads(chunk.decode("ascii"))
            lines.append(event)
            if on_line:
                on_line(event, proc)
        code = proc.wait()
    finally:
        timer.cancel()
        if proc.stdin:
            try:
                proc.stdin.close()
            except OSError:
                pass
        drain.join(timeout=10)
    elapsed = time.perf_counter() - started
    stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    return CliRun(code, lines, raw, stderr, elapsed)


def _ffmpeg(*args):
    subprocess.run(
        [shorts_core.ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
        **NO_WINDOW,
    )


class CliVersionTests(unittest.TestCase):
    def test_version(self):
        run = run_cli("version")
        self.assertEqual(run.code, 0, run.stderr)
        self.assertEqual(len(run.lines), 1)
        first = (ROOT / "VERSION.txt").read_text(encoding="utf-8-sig").splitlines()[0]
        expected = re.search(r"v(\d+\.\d+\.\d+)", first).group(1)
        self.assertEqual(
            run.last,
            {"event": "version", "engine": "shorts", "version": expected, "job_schema": "shorts_job.v1"},
        )
        self.assertTrue(run.raw.isascii())


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg/ffprobe are not available")
class CliRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shorts_cli_"))
        cls.src = cls.tmp / "src"
        cls.src.mkdir()
        cls.silent_bg = cls.src / "loop_silent.mp4"
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=5",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(cls.silent_bg))
        cls.loud_bg = cls.src / "loop_tone.mp4"
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=6",
                "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=6",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", str(cls.loud_bg))
        cls.audio40 = cls.src / "silence_40s.wav"
        _ffmpeg("-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-t", "40", str(cls.audio40))
        cls.rhythm60 = cls.src / "rhythm_60s.wav"
        _ffmpeg("-f", "lavfi", "-i",
                "aevalsrc='0.6*sin(2*PI*440*t)*exp(-20*mod(t\\,0.5))*(0.3+0.7*between(t\\,25\\,45))'"
                ":s=48000:d=60", "-ac", "2", str(cls.rhythm60))
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        report = os.environ.get("SHORTS_CLI_REPORT")
        if report:
            Path(report).write_text(json.dumps(REPORT, indent=2, ensure_ascii=False), encoding="utf-8")

    def job(self, folder=None, filename="job.json", **fields):
        type(self).counter += 1
        folder = folder or (self.tmp / f"job{self.counter}")
        folder.mkdir(parents=True, exist_ok=True)
        data = {
            "schema": "shorts_job.v1",
            "audio": str(self.audio40),
            "background": str(self.silent_bg),
            "output": str(folder / "out" / "short.mp4"),
            "duration": 15,
            "start": 5,
            "fit_mode": "crop",
            "fade_sec": 0,
        }
        data.update(fields)
        data = {k: v for k, v in data.items() if v is not None}
        path = folder / filename
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path, folder

    def assert_error(self, run, code, exit_code):
        self.assertEqual(run.code, exit_code, run.stderr)
        self.assertEqual(run.last["event"], "error")
        self.assertFalse(run.last["ok"])
        self.assertEqual(run.last["code"], code)
        self.assertTrue(run.last["message"])
        self.assertTrue(run.raw.isascii())

    def assert_no_outputs(self, folder):
        self.assertEqual([p.name for p in folder.rglob("*.mp4")], [])

    def assert_success(self, run):
        self.assertEqual(run.code, 0, run.stderr + json.dumps(run.lines[-1:], ensure_ascii=False))
        self.assertTrue(run.raw.isascii())
        self.assertEqual(run.lines[0]["event"], "start")
        self.assertEqual(run.last["event"], "result")
        self.assertTrue(run.last["ok"])
        self.assertTrue(Path(run.last["output"]).is_file())
        self.assertEqual([p.name for p in Path(run.last["output"]).parent.glob("*.part*")], [])
        return run.last

    # ------------------------------------------------------------- invalid

    def test_invalid_job_cases(self):
        cases = {
            "schema_missing": dict(schema=None),
            "duration_70": dict(duration=70),
            "fit_mode_x": dict(fit_mode="x"),
        }
        for name, fields in cases.items():
            with self.subTest(case=name):
                job, folder = self.job(**fields)
                run = run_cli("render", "--job", job)
                self.assert_error(run, "invalid_job", 2)
                self.assert_no_outputs(folder)

    def test_input_not_found(self):
        job, folder = self.job(audio=str(self.src / "없는_음원.wav"))
        run = run_cli("render", "--job", job)
        self.assert_error(run, "input_not_found", 3)
        self.assertIn("\\u", run.raw.decode("ascii"))  # Korean text is escaped, not raw UTF-8

    def test_highlight_out_of_range_is_fast(self):
        job, folder = self.job(start=30, duration=20)
        run = run_cli("render", "--job", job)
        self.assert_error(run, "highlight_out_of_range", 2)
        self.assertLess(run.elapsed, 3.0)
        self.assertIn("30.0~50.0", run.last["message"])
        self.assert_no_outputs(folder)
        REPORT["highlight_out_of_range_sec"] = round(run.elapsed, 3)

    def test_audio_too_short(self):
        job, folder = self.job(start="auto", duration=45)
        run = run_cli("render", "--job", job)
        self.assert_error(run, "audio_too_short", 2)
        self.assert_no_outputs(folder)

    # ------------------------------------------------------------- render

    def test_render_numeric_start(self):
        job, folder = self.job(start=5)
        run = run_cli("render", "--job", job)
        result = self.assert_success(run)
        progress = [e["value"] for e in run.events("progress")]
        self.assertGreaterEqual(len(progress), 3)
        self.assertEqual(progress, sorted(set(progress)))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in progress))
        self.assertEqual(progress[-1], 1.0)
        self.assertEqual(run.lines[0]["start"], 5)
        self.assertEqual(result["start"], 5)
        self.assertAlmostEqual(result["duration"], 15, delta=0.5)
        self.assertEqual(result["fit_mode"], "crop")
        self.assertFalse(result["background_had_audio"])
        self.assertEqual(result["warnings"], [])
        self.assertGreater(result["elapsed_sec"], 0)
        REPORT["numeric_render"] = {"elapsed_sec": result["elapsed_sec"], "progress_events": len(progress)}

    def test_relative_paths_resolve_from_job_folder(self):
        folder = self.tmp / "relative"
        folder.mkdir()
        shutil.copy(self.audio40, folder / "song.wav")
        (folder / "bg").mkdir()
        shutil.copy(self.silent_bg, folder / "bg" / "lake.mp4")
        job, _ = self.job(folder=folder, audio="song.wav", background="bg/lake.mp4", output="out/song_short.mp4")
        run = run_cli("render", "--job", job)  # cwd is the repo root, not the job folder
        result = self.assert_success(run)
        self.assertEqual(Path(result["output"]), (folder / "out" / "song_short.mp4").resolve())

    def test_unknown_keys_are_warnings(self):
        job, _ = self.job(future_option=True, caption_theme="x")
        result = self.assert_success(run_cli("render", "--job", job))
        self.assertIn("unknown_key:future_option", result["warnings"])
        self.assertIn("unknown_key:caption_theme", result["warnings"])

    def test_background_audio_warning(self):
        job, _ = self.job(background=str(self.loud_bg))
        result = self.assert_success(run_cli("render", "--job", job))
        self.assertIn("background_audio_ignored", result["warnings"])
        self.assertTrue(result["background_had_audio"])

    @unittest.skipUnless(shorts_core.librosa is not None, "librosa is not installed")
    def test_render_auto_start(self):
        job, _ = self.job(audio=str(self.rhythm60), start="auto", duration=20, highlight_rank=1)
        run = run_cli("render", "--job", job)
        result = self.assert_success(run)
        self.assertIsInstance(result["start"], (int, float))
        self.assertLessEqual(result["start"] + 20, 60.0 + 0.05)
        self.assertEqual(run.lines[0]["start"], result["start"])
        REPORT["auto_start"] = {"start": result["start"], "elapsed_sec": result["elapsed_sec"],
                                "wall_sec": round(run.elapsed, 2)}

    @unittest.skipUnless(shorts_core.librosa is not None, "librosa is not installed")
    def test_analyze(self):
        run = run_cli("analyze", "--audio", self.rhythm60, "--duration", 20)
        self.assertEqual(run.code, 0, run.stderr)
        self.assertEqual(len(run.lines), 1)
        self.assertTrue(run.raw.isascii())
        event = run.last
        self.assertEqual(event["event"], "highlights")
        self.assertTrue(1 <= len(event["items"]) <= 3)
        for rank, item in enumerate(event["items"], 1):
            self.assertEqual(item["rank"], rank)
            self.assertEqual(set(item), {"rank", "start", "end", "duration", "score", "reason"})
            self.assertLessEqual(item["start"] + item["duration"], 60.0 + 1e-6)
            self.assertGreaterEqual(item["start"], 0)
        REPORT["analyze_items"] = event["items"]

    # ------------------------------------------------------------- cancel

    def _cancel_after_start(self, action):
        job, folder = self.job(duration=30, fit_mode="blur", start=0)
        timing = {}

        def on_line(event, proc):
            if event["event"] == "start":
                time.sleep(1.0)
                timing["sent"] = time.perf_counter()
                action(proc)

        run = run_cli("render", "--job", job, on_line=on_line)
        self.assert_error(run, "cancelled", 5)
        self.assert_no_outputs(folder)
        self.assertEqual(list(folder.rglob("*.part*")), [])
        return round(time.perf_counter() - timing["sent"], 2)

    def test_cancel_via_stdin_line(self):
        def send_cancel(proc):
            proc.stdin.write(b"cancel\n")
            proc.stdin.flush()

        REPORT["cancel_line_exit_sec"] = self._cancel_after_start(send_cancel)

    def test_cancel_via_stdin_eof(self):
        REPORT["cancel_eof_exit_sec"] = self._cancel_after_start(lambda proc: proc.stdin.close())

    def test_null_stdin_means_cancelled(self):
        job, folder = self.job()
        run = run_cli("render", "--job", job, stdin=subprocess.DEVNULL)
        self.assert_error(run, "cancelled", 5)
        self.assert_no_outputs(folder)

    def test_no_stdin_cancel_ignores_null_stdin(self):
        job, _ = self.job()
        self.assert_success(run_cli("render", "--job", job, "--no-stdin-cancel", stdin=subprocess.DEVNULL))


if __name__ == "__main__":
    unittest.main()
