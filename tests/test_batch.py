"""shorts_cli.py batch (shorts_batch.v1) -- every test runs the real CLI in a subprocess.

Set SHORTS_BATCH_REPORT=<path.json> to dump timings.
"""

import csv
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from test_cli import HAS_FFMPEG, _ffmpeg, run_cli

CSV_COLUMNS = [
    "index", "audio", "background", "video_offset", "start", "duration",
    "fit_mode", "status", "output", "code", "message", "elapsed_sec",
]
REPORT = {}


def _silence(path, seconds):
    _ffmpeg("-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", str(seconds), str(path))


def _clip(path, seconds, size="1280x720"):
    _ffmpeg("-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path))


def _read_csv(path):
    raw = Path(path).read_bytes()
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return raw, reader.fieldnames, list(reader)


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg/ffprobe are not available")
class BatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="shorts_batch_"))
        cls.src = cls.tmp / "src"
        cls.src.mkdir()
        cls.bg_dir = cls.src / "bg"
        cls.bg_dir.mkdir()
        _clip(cls.bg_dir / "bg1.mp4", 5)
        _clip(cls.bg_dir / "bg2.mp4", 6)
        (cls.bg_dir / "notes.txt").write_text("ignored", encoding="utf-8")
        cls.song = cls.src / "song_20s.wav"
        _silence(cls.song, 20)
        cls.counter = 0

        # One 3-song run shared by the rotate / natural sort / failure / CSV / name tests.
        cls.main_dir = cls.tmp / "main"
        audio = cls.main_dir / "songs"
        (audio / "sub").mkdir(parents=True)
        shutil.copy(cls.song, audio / "10 - y.wav")
        shutil.copy(cls.song, audio / "1 - a.wav")
        (audio / "2 - broken.wav").write_bytes(b"this is not audio")
        shutil.copy(cls.song, audio / "sub" / "0 - nested.wav")  # sub folders are not scanned
        job = cls.write_job(cls.main_dir, audio_dir="songs", background_dir=str(cls.bg_dir),
                            name_template='{index}_{stem}<>:"|?*')
        cls.main = run_cli("batch", "--job", job)
        REPORT["main_wall_sec"] = round(cls.main.elapsed, 2)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        report = os.environ.get("SHORTS_BATCH_REPORT")
        if report:
            Path(report).write_text(json.dumps(REPORT, indent=2), encoding="utf-8")

    @classmethod
    def write_job(cls, folder, **fields):
        folder.mkdir(parents=True, exist_ok=True)
        data = {
            "schema": "shorts_batch.v1",
            "output_dir": "out",
            "duration": 15,
            "start": 0,
            "fit_mode": "crop",
            "fade_sec": 0,
            "assign": "rotate",
            "video_offset": 0,
        }
        data.update(fields)
        data = {k: v for k, v in data.items() if v is not None}
        path = folder / "batch.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def new_folder(self):
        type(self).counter += 1
        return self.tmp / f"case{self.counter}"

    def songs(self, folder, names):
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copy(self.song, folder / name)
        return folder

    def assert_ascii(self, run):
        self.assertTrue(run.raw.isascii())

    # ------------------------------------------------ shared 3-song run

    def test_main_run_exit_and_counts(self):
        run = self.main
        self.assert_ascii(run)
        self.assertEqual(run.code, 6, run.stderr)
        result = run.last
        self.assertEqual(result["event"], "batch_result")
        self.assertEqual((result["ok"], result["done"], result["failed"], result["skipped"]), (False, 2, 1, 0))
        self.assertNotIn("cancelled_remaining", result)

    def test_natural_sort_and_no_subfolders(self):
        names = [Path(e["audio"]).name for e in self.main.events("item_start")]
        self.assertEqual(names, ["1 - a.wav", "2 - broken.wav", "10 - y.wav"])
        self.assertEqual(self.main.events("batch_start")[0]["total"], 3)

    def test_rotate_assignment(self):
        assigned = [Path(e["background"]).name for e in self.main.events("item_start")]
        self.assertEqual(assigned, ["bg1.mp4", "bg2.mp4", "bg1.mp4"])

    def test_failure_does_not_stop_batch(self):
        results = {e["index"]: e for e in self.main.events("item_result")}
        self.assertTrue(results[1]["ok"])
        self.assertFalse(results[2]["ok"])
        self.assertTrue(results[2]["code"])
        self.assertTrue(results[3]["ok"])
        for index in (1, 3):
            self.assertTrue(Path(results[index]["output"]).is_file())
        progress = self.main.events("progress")
        self.assertTrue(all("index" in e and "overall" in e for e in progress))
        overall = [e["overall"] for e in progress]
        self.assertEqual(overall, sorted(overall))

    def test_csv_log(self):
        raw, header, rows = _read_csv(self.main.last["csv"])
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(header, CSV_COLUMNS)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["status"] for r in rows], ["ok", "failed", "ok"])
        self.assertEqual(sum(r["status"] == "failed" for r in rows), 1)
        self.assertEqual(rows[1]["code"], self.main.events("item_result")[1]["code"])
        self.assertTrue(rows[1]["message"])
        self.assertEqual(rows[0]["fit_mode"], "crop")
        self.assertEqual(float(rows[0]["duration"]), 15.0)
        self.assertRegex(Path(self.main.last["csv"]).name, r"^shorts_batch_\d{8}_\d{6}(_\d+)?\.csv$")

    def test_name_template_index_and_forbidden_chars(self):
        outputs = [Path(e["output"]).name for e in self.main.events("item_result") if e["ok"]]
        self.assertEqual(outputs, ["01_1 - a.mp4", "03_10 - y.mp4"])
        for name in outputs:
            self.assertFalse(set('<>:"|?*') & set(name))

    def test_no_part_files_left(self):
        self.assertEqual(list(self.main_dir.rglob("*.part*")), [])

    # ------------------------------------------------ random assignment

    def test_random_assignment_is_reproducible_without_repeats(self):
        folder = self.new_folder()
        audio = self.songs(folder / "songs", [f"{i} - s.wav" for i in range(1, 7)])
        bg = folder / "bg"
        bg.mkdir()
        for name in ("b1.mp4", "b2.mp4", "b3.mp4"):
            shutil.copy(self.bg_dir / "bg2.mp4", bg / name)
        out = folder / "out"
        out.mkdir()
        for i in range(1, 7):  # outputs exist -> everything is skipped, so no rendering is needed
            (out / f"{i} - s_short.mp4").write_bytes(b"x")
        job = self.write_job(folder, audio_dir=str(audio), background_dir=str(bg), assign="random",
                             seed=1234, video_offset="random", name_template=None)
        runs = [run_cli("batch", "--job", job) for _ in range(2)]
        plans = []
        for run in runs:
            self.assert_ascii(run)
            self.assertEqual(run.code, 0, run.stderr)
            self.assertEqual(run.events("batch_start")[0]["seed"], 1234)
            plans.append([(Path(e["background"]).name, e["video_offset"]) for e in run.events("item_start")])
        self.assertEqual(plans[0], plans[1])
        names = [name for name, _ in plans[0]]
        self.assertEqual(len(names), 6)
        self.assertTrue(all(a != b for a, b in zip(names, names[1:])), names)
        self.assertEqual(set(names), {"b1.mp4", "b2.mp4", "b3.mp4"})
        offsets = [offset for _, offset in plans[0]]
        self.assertTrue(all(0.0 <= o <= 5.0 for o in offsets), offsets)  # clip is 6 s -> 0..5
        self.assertGreater(len(set(offsets)), 1)

        other = self.write_job(folder, audio_dir=str(audio), background_dir=str(bg), assign="random",
                               seed=None, video_offset="random", name_template=None)
        auto_seed = run_cli("batch", "--job", other).events("batch_start")[0]["seed"]
        self.assertIsInstance(auto_seed, int)

    # ------------------------------------------------ skip / numbering

    def test_skip_existing_second_run_renders_nothing(self):
        folder = self.new_folder()
        audio = self.songs(folder / "songs", ["1 - a.wav", "2 - b.wav"])
        job = self.write_job(folder, audio_dir=str(audio), background_dir=str(self.bg_dir))
        first = run_cli("batch", "--job", job)
        self.assertEqual(first.code, 0, first.stderr)
        self.assertEqual(first.last["done"], 2)
        second = run_cli("batch", "--job", job)
        self.assert_ascii(second)
        self.assertEqual(second.code, 0, second.stderr)
        self.assertEqual((second.last["done"], second.last["skipped"], second.last["failed"]), (0, 2, 0))
        self.assertTrue(all(e.get("skipped") for e in second.events("item_result")))
        self.assertEqual(second.events("progress"), [])
        self.assertLess(second.elapsed, 5.0)
        self.assertNotEqual(first.last["csv"], second.last["csv"])
        _, _, rows = _read_csv(second.last["csv"])
        self.assertEqual([r["status"] for r in rows], ["skipped", "skipped"])
        REPORT["skip_first_sec"] = round(first.elapsed, 2)
        REPORT["skip_second_sec"] = round(second.elapsed, 2)

        again = self.write_job(folder, audio_files=["songs/1 - a.wav"], background_files=[str(self.bg_dir / "bg1.mp4")],
                               skip_existing=False)
        third = run_cli("batch", "--job", again)
        self.assertEqual(third.code, 0, third.stderr)
        self.assertEqual(Path(third.events("item_result")[0]["output"]).name, "1 - a_short_1.mp4")

    # ------------------------------------------------ cancel

    def test_cancel_during_second_song(self):
        folder = self.new_folder()
        audio = self.songs(folder / "songs", ["1 - a.wav", "2 - b.wav", "3 - c.wav"])
        job = self.write_job(folder, audio_dir=str(audio), background_dir=str(self.bg_dir))

        def on_line(event, proc):
            if event["event"] == "item_start" and event["index"] == 2:
                time.sleep(1.0)
                proc.stdin.write(b"cancel\n")
                proc.stdin.flush()

        run = run_cli("batch", "--job", job, on_line=on_line)
        self.assert_ascii(run)
        self.assertEqual(run.code, 5, run.stderr)
        result = run.last
        self.assertEqual(result["event"], "batch_result")
        self.assertFalse(result["ok"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["cancelled_remaining"], 2)
        self.assertEqual(result["done"], 1)
        self.assertEqual([e["index"] for e in run.events("item_result")], [1])
        outputs = sorted(p.name for p in (folder / "out").glob("*.mp4"))
        self.assertEqual(outputs, ["1 - a_short.mp4"])
        self.assertEqual(list(folder.rglob("*.part*")), [])
        _, _, rows = _read_csv(result["csv"])
        self.assertEqual([r["status"] for r in rows], ["ok", "cancelled"])

    # ------------------------------------------------ invalid input

    def test_invalid_jobs(self):
        folder = self.new_folder()
        audio = self.songs(folder / "songs", ["1 - a.wav"])
        (folder / "empty").mkdir()
        cases = {
            "both_audio_sources": dict(audio_dir=str(audio), audio_files=["songs/1 - a.wav"],
                                       background_dir=str(self.bg_dir)),
            "empty_audio_folder": dict(audio_dir="empty", background_dir=str(self.bg_dir)),
            "empty_background_folder": dict(audio_dir=str(audio), background_dir="empty"),
            "no_audio_source": dict(background_dir=str(self.bg_dir)),
            "bad_assign": dict(audio_dir=str(audio), background_dir=str(self.bg_dir), assign="shuffle"),
            "bad_template_key": dict(audio_dir=str(audio), background_dir=str(self.bg_dir), name_template="{song}"),
            "duplicate_names": dict(audio_files=["songs/1 - a.wav", "songs/1 - a.wav"],
                                    background_dir=str(self.bg_dir), name_template="same"),
            "duration_70": dict(audio_dir=str(audio), background_dir=str(self.bg_dir), duration=70),
        }
        for name, fields in cases.items():
            with self.subTest(case=name):
                run = run_cli("batch", "--job", self.write_job(folder, **fields))
                self.assert_ascii(run)
                self.assertEqual(run.code, 2, run.stderr)
                self.assertEqual(run.last["event"], "error")
                self.assertEqual(run.last["code"], "invalid_job")
        self.assertFalse((folder / "out").exists())

    def test_missing_folder_is_input_not_found(self):
        folder = self.new_folder()
        run = run_cli("batch", "--job", self.write_job(folder, audio_dir="nope", background_dir=str(self.bg_dir)))
        self.assert_ascii(run)
        self.assertEqual(run.code, 3, run.stderr)
        self.assertEqual(run.last["code"], "input_not_found")


if __name__ == "__main__":
    unittest.main()
