"""Video background renderer (v0.7.0) tests.

A. command construction (no FFmpeg needed)
B. image-mode regression pin for build_render_short_command
C. FFmpeg integration (skipped only when FFmpeg/ffprobe are missing)

Set SHORTS_VIDEO_BG_REPORT=<path.json> to dump the integration matrix
(duration, frames, mean_volume, blackdetect, render seconds) to a file.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import shorts_core

SOCIAL_ARGS = [
    ("-c:v", "libx264"),
    ("-pix_fmt", "yuv420p"),
    ("-colorspace", "bt709"),
    ("-color_primaries", "bt709"),
    ("-color_trc", "bt709"),
    ("-r", "30"),
    ("-fps_mode:v", "cfr"),
    ("-c:a", "aac"),
    ("-profile:a", "aac_low"),
    ("-ar", "48000"),
    ("-ac", "2"),
    ("-movflags", "+faststart"),
]


def _build(**kw):
    args = dict(
        audio_path="music.wav",
        video_path="bg.mp4",
        output_path="out.mp4",
        start=10,
        duration=20,
        nvenc_available_fn=lambda: False,
    )
    args.update(kw)
    with mock.patch.object(shorts_core, "ffmpeg_path", return_value="ffmpeg"):
        return shorts_core.build_render_video_short_command(**args)


def _value(cmd, option):
    return cmd[cmd.index(option) + 1]


def _map_values(cmd):
    return [cmd[i + 1] for i, part in enumerate(cmd) if part == "-map"]


class VideoCommandTests(unittest.TestCase):
    def test_stream_loop_precedes_background_input(self):
        cmd = _build(video_offset=2.5)
        loop = cmd.index("-stream_loop")
        self.assertEqual(cmd[loop + 1], "-1")
        inputs = [i for i, part in enumerate(cmd) if part == "-i"]
        self.assertEqual(cmd[inputs[0] + 1], "bg.mp4")
        self.assertEqual(cmd[inputs[1] + 1], "music.wav")
        self.assertLess(loop, inputs[0])
        self.assertEqual(cmd[inputs[0] - 2 : inputs[0]], ["-ss", "2.500"])
        self.assertEqual(cmd[inputs[1] - 2 : inputs[1]], ["-ss", "10.000"])

    def test_maps_only_filtered_video_and_music_audio(self):
        for fit_mode in ("crop", "blur"):
            with self.subTest(fit_mode=fit_mode):
                cmd = _build(fit_mode=fit_mode)
                self.assertEqual(_map_values(cmd), ["[v]", "1:a:0"])
                self.assertFalse([part for part in cmd if "0:a" in part])
                self.assertIn("-filter_complex", cmd)
                self.assertTrue(_value(cmd, "-filter_complex").endswith("[v]"))
                self.assertEqual(_value(cmd, "-t"), "20.000")

    def test_social_encode_arguments_present(self):
        for fit_mode in ("crop", "blur"):
            cmd = _build(fit_mode=fit_mode)
            for option, expected in SOCIAL_ARGS:
                with self.subTest(fit_mode=fit_mode, option=option):
                    self.assertEqual(_value(cmd, option), expected)
            graph = _value(cmd, "-filter_complex")
            self.assertIn("format=yuv420p", graph)
            self.assertIn("colorspace=bt709", graph)
            self.assertIn("aresample=48000", _value(cmd, "-af"))

    def test_social_helpers_are_reused_verbatim(self):
        cmd = _build(fade_sec=0)
        tail = (
            shorts_core.social_video_encode_args(nvenc_available_fn=lambda: False)
            + shorts_core.social_audio_encode_args()
            + shorts_core.social_mp4_output_args()
            + ["out.mp4"]
        )
        self.assertEqual(cmd[-len(tail) :], tail)
        self.assertEqual(_value(cmd, "-af"), shorts_core.social_audio_filter("anull"))

    def test_blur_mode_uses_explicit_split(self):
        graph = _value(_build(fit_mode="blur"), "-filter_complex")
        self.assertIn("split=2[bgsrc][fgsrc]", graph)
        self.assertEqual(graph.count("[0:v:0]"), 1)
        self.assertIn("boxblur=30:5", graph)
        self.assertIn("force_original_aspect_ratio=decrease", graph)
        self.assertIn("overlay=(W-w)/2:(H-h)/2", graph)

    def test_crop_mode_scales_and_center_crops(self):
        graph = _value(_build(fit_mode="crop"), "-filter_complex")
        self.assertTrue(graph.startswith("[0:v:0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"))
        self.assertNotIn("split", graph)

    def test_fade_rules_match_image_mode(self):
        cmd = _build(duration=20, fade_sec=10)
        self.assertIn("fade=t=in:st=0:d=5.0,fade=t=out:st=15.0:d=5.0", _value(cmd, "-filter_complex"))
        self.assertTrue(_value(cmd, "-af").startswith("afade=t=in:st=0:d=5.0,afade=t=out:st=15.0:d=5.0"))
        no_fade = _build(fade_sec=0)
        self.assertNotIn("fade=", _value(no_fade, "-filter_complex"))
        self.assertTrue(_value(no_fade, "-af").startswith("anull"))

    def test_subtitles_only_when_srt_exists(self):
        self.assertNotIn("subtitles=", _value(_build(subtitle_path="missing.srt"), "-filter_complex"))
        with tempfile.TemporaryDirectory() as tmp:
            srt = Path(tmp) / "lyrics.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
            graph = _value(_build(subtitle_path=str(srt)), "-filter_complex")
        self.assertIn(f"subtitles='{shorts_core._filter_path(srt)}'", graph)
        self.assertIn("force_style='", graph)

    def test_invalid_arguments_raise_value_error(self):
        cases = [
            dict(fit_mode="stretch"),
            dict(duration=10),
            dict(duration=70),
            dict(video_offset=-1),
        ]
        for case in cases:
            with self.subTest(**case):
                with self.assertRaises(ValueError):
                    _build(**case)
        self.assertTrue(_build(duration=15))
        self.assertTrue(_build(duration=60))

    def test_render_rejects_output_equal_to_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "music.wav"
            video = Path(tmp) / "bg.mp4"
            audio.write_bytes(b"x")
            video.write_bytes(b"x")
            for target in (audio, video):
                with self.subTest(target=target.name):
                    with self.assertRaises(ValueError):
                        shorts_core.render_video_short(audio, video, target, 0, 20)


# Generated from the main-branch build_render_short_command. If this test
# breaks, the image background mode changed: that is a regression.
IMAGE_MODE_FILL_EXPECTED = [
    'ffmpeg',
    '-y',
    '-hide_banner',
    '-loglevel',
    'error',
    '-loop',
    '1',
    '-framerate',
    '30',
    '-i',
    'image.jpg',
    '-ss',
    '12.500',
    '-i',
    'audio.wav',
    '-vf',
    "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(1.0+(0.06000000*on/1349),1.06000)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,fade=t=in:st=0:d=0.5,fade=t=out:st=44.5:d=0.5,fps=fps=30:round=near,scale=1080:1920:flags=lanczos:in_range=auto:out_range=tv:out_color_matrix=bt709,setsar=1,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,setpts=N/(30*TB)",
    '-map',
    '0:v:0',
    '-map',
    '1:a:0',
    '-af',
    'afade=t=in:st=0:d=0.5,afade=t=out:st=44.5:d=0.5,aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo',
    '-t',
    '45.000',
    '-c:v',
    'libx264',
    '-preset',
    'medium',
    '-crf',
    '18',
    '-pix_fmt',
    'yuv420p',
    '-profile:v',
    'high',
    '-level:v',
    '4.1',
    '-colorspace',
    'bt709',
    '-color_primaries',
    'bt709',
    '-color_trc',
    'bt709',
    '-color_range',
    'tv',
    '-r',
    '30',
    '-fps_mode:v',
    'cfr',
    '-c:a',
    'aac',
    '-profile:a',
    'aac_low',
    '-b:a',
    '192k',
    '-ar',
    '48000',
    '-ac',
    '2',
    '-map_metadata',
    '-1',
    '-map_chapters',
    '-1',
    '-movflags',
    '+faststart',
    '-avoid_negative_ts',
    'make_zero',
    '-shortest',
    'out.mp4',
]

IMAGE_MODE_BLUR_EXPECTED = [
    'ffmpeg',
    '-y',
    '-hide_banner',
    '-loglevel',
    'error',
    '-loop',
    '1',
    '-framerate',
    '30',
    '-i',
    'image.jpg',
    '-ss',
    '3.000',
    '-i',
    'audio.wav',
    '-filter_complex',
    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5[bg];[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,zoompan=z='1.08875+0.004000*max(0,sin(2*PI*on/75.000))':x='(iw-iw/zoom)*(on/899)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30,noise=alls=4:allf=t+u,fade=t=in:st=0:d=1.0,fade=t=out:st=29.0:d=1.0,fps=fps=30:round=near,scale=1080:1920:flags=lanczos:in_range=auto:out_range=tv:out_color_matrix=bt709,setsar=1,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,setpts=N/(30*TB)[v]",
    '-map',
    '[v]',
    '-map',
    '1:a:0',
    '-af',
    'afade=t=in:st=0:d=1.0,afade=t=out:st=29.0:d=1.0,aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo',
    '-t',
    '30.000',
    '-c:v',
    'libx264',
    '-preset',
    'medium',
    '-crf',
    '18',
    '-pix_fmt',
    'yuv420p',
    '-profile:v',
    'high',
    '-level:v',
    '4.1',
    '-colorspace',
    'bt709',
    '-color_primaries',
    'bt709',
    '-color_trc',
    'bt709',
    '-color_range',
    'tv',
    '-r',
    '30',
    '-fps_mode:v',
    'cfr',
    '-c:a',
    'aac',
    '-profile:a',
    'aac_low',
    '-b:a',
    '192k',
    '-ar',
    '48000',
    '-ac',
    '2',
    '-map_metadata',
    '-1',
    '-map_chapters',
    '-1',
    '-movflags',
    '+faststart',
    '-avoid_negative_ts',
    'make_zero',
    '-shortest',
    'out.mp4',
]


class ImageModeRegressionTests(unittest.TestCase):
    def test_fill_command_is_pinned(self):
        with mock.patch.object(shorts_core, "ffmpeg_path", return_value="ffmpeg"):
            cmd = shorts_core.build_render_short_command(
                "audio.wav",
                "image.jpg",
                "out.mp4",
                12.5,
                45,
                mode="fill",
                zoom_pct=6.0,
                fade_sec=0.5,
                motion_pattern="slow_zoom_in",
                nvenc_available_fn=lambda: False,
            )
        self.assertEqual(cmd, IMAGE_MODE_FILL_EXPECTED)

    def test_blur_command_is_pinned(self):
        with mock.patch.object(shorts_core, "ffmpeg_path", return_value="ffmpeg"):
            cmd = shorts_core.build_render_short_command(
                "audio.wav",
                "image.jpg",
                "out.mp4",
                3,
                30,
                mode="blur",
                fade_sec=1.0,
                motion_pattern="pan_left_to_right",
                motion_intensity="strong",
                beat_reactivity="weak",
                overlay_effect="film_grain",
                nvenc_available_fn=lambda: False,
            )
        self.assertEqual(cmd, IMAGE_MODE_BLUR_EXPECTED)


# ---------------------------------------------------------------- integration

def _tools():
    ffmpeg = shorts_core.ffmpeg_path()
    ffprobe = shorts_core.ffprobe_path()
    if not ffmpeg or not ffprobe:
        return None
    if not (Path(ffmpeg).exists() or shutil.which(ffmpeg)):
        return None
    return ffmpeg, ffprobe


TOOLS = _tools()
BACKGROUNDS = {
    "a": dict(size="1920x1080", seconds=8, tone=True),
    "b": dict(size="1080x1920", seconds=8, tone=False),
    "c": dict(size="1280x720", seconds=5, tone=False),
}
FIT_MODES = ("crop", "blur")
RENDER_SECONDS = 20


def _run(cmd):
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-3000:])
    return p.stdout + p.stderr


def _make_background(ffmpeg, path, size, seconds, tone):
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}"]
    if tone:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=1000:sample_rate=48000:duration={seconds}",
                "-af", "volume=8", "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-t", str(seconds), str(path)]
    _run(cmd)


def _frame_count(ffprobe, path):
    out = _run([ffprobe, "-v", "error", "-count_packets", "-select_streams", "v:0",
                "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)])
    return int(out.strip().splitlines()[0])


def _mean_volume(ffmpeg, path):
    out = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                "-af", "volumedetect", "-f", "null", "-"])
    match = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", out)
    if not match:
        raise AssertionError("volumedetect produced no mean_volume")
    return float("-inf") if match.group(1) == "-inf" else float(match.group(1))


def _black_segments(ffmpeg, path):
    out = _run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:v:0",
                "-vf", "blackdetect=d=0.1:pix_th=0.05", "-an", "-f", "null", "-"])
    return re.findall(r"black_start:\S+ black_end:\S+ black_duration:\S+", out)


def _video_md5(ffmpeg, path):
    return _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:v:0",
                 "-f", "md5", "-"]).strip()


@unittest.skipUnless(TOOLS, "FFmpeg/ffprobe are not available")
class VideoBackgroundIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffmpeg, cls.ffprobe = TOOLS
        cls.tmp = Path(tempfile.mkdtemp(prefix="shorts_video_bg_"))
        cls.src = cls.tmp / "src"
        cls.out = cls.tmp / "out"
        cls.src.mkdir()
        cls.out.mkdir()
        cls.backgrounds = {}
        for name, spec in BACKGROUNDS.items():
            path = cls.src / f"bg_{name}.mp4"
            _make_background(cls.ffmpeg, path, **spec)
            cls.backgrounds[name] = path
        cls.audio = cls.src / "music.wav"
        _run([cls.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
              "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", "40", str(cls.audio)])

        cls.matrix = {}
        for name, bg in cls.backgrounds.items():
            for fit_mode in FIT_MODES:
                key = f"{name}-{fit_mode}"
                started = time.perf_counter()
                try:
                    result = shorts_core.render_video_short(
                        cls.audio, bg, cls.out / f"{key}.mp4", 5, RENDER_SECONDS,
                        fit_mode=fit_mode, fade_sec=0,
                    )
                    error = None
                except Exception as exc:  # reported per test below
                    result, error = None, exc
                cls.matrix[key] = {
                    "result": result,
                    "error": error,
                    "seconds": round(time.perf_counter() - started, 2),
                }
        for entry in cls.matrix.values():
            if entry["result"]:
                path = entry["result"]["output"]
                entry["frames"] = _frame_count(cls.ffprobe, path)
                entry["mean_volume"] = _mean_volume(cls.ffmpeg, path)
                entry["black"] = _black_segments(cls.ffmpeg, path)

        report = os.environ.get("SHORTS_VIDEO_BG_REPORT")
        if report:
            rows = {
                key: {
                    "seconds": e["seconds"],
                    "error": str(e["error"]) if e["error"] else None,
                    "duration": e["result"]["duration"] if e["result"] else None,
                    "frames": e.get("frames"),
                    "mean_volume": e.get("mean_volume"),
                    "black": e.get("black"),
                    "background_had_audio": e["result"]["background_had_audio"] if e["result"] else None,
                    "compatible": e["result"]["validation"]["compatible"] if e["result"] else None,
                    "resolution": e["result"]["validation"]["resolution"] if e["result"] else None,
                }
                for key, e in cls.matrix.items()
            }
            rows["_source_a_mean_volume"] = _mean_volume(cls.ffmpeg, cls.backgrounds["a"])
            Path(report).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _entries(self):
        for key, entry in self.matrix.items():
            with self.subTest(combo=key):
                if entry["error"]:
                    self.fail(f"render failed: {entry['error']}")
                yield key, entry

    def test_probe_reports_background_audio(self):
        a = shorts_core.probe_background_video(self.backgrounds["a"])
        self.assertTrue(a["has_audio"])
        self.assertEqual((a["width"], a["height"]), (1920, 1080))
        self.assertAlmostEqual(a["duration"], 8, delta=0.1)
        self.assertAlmostEqual(a["fps"], 30, delta=0.01)
        self.assertFalse(shorts_core.probe_background_video(self.backgrounds["c"])["has_audio"])

    def test_probe_rejects_audio_only_and_too_short(self):
        with self.assertRaises(ValueError):
            shorts_core.probe_background_video(self.audio)
        tiny = self.src / "tiny.mp4"
        _run([self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
              "-i", "testsrc2=size=320x240:rate=30:duration=0.5", "-pix_fmt", "yuv420p", str(tiny)])
        with self.assertRaises(ValueError):
            shorts_core.probe_background_video(tiny)

    def test_matrix_outputs_are_social_compatible(self):
        for key, entry in self._entries():
            validation = entry["result"]["validation"]
            self.assertTrue(validation["compatible"], validation["issues"])
            self.assertEqual(validation["resolution"], "1080x1920")

    def test_matrix_duration_and_frame_count(self):
        for key, entry in self._entries():
            self.assertAlmostEqual(entry["result"]["duration"], RENDER_SECONDS, delta=0.5)
            self.assertAlmostEqual(entry["frames"], RENDER_SECONDS * 30, delta=2)

    def test_background_audio_never_reaches_output(self):
        self.assertGreater(_mean_volume(self.ffmpeg, self.backgrounds["a"]), -30)
        for key, entry in self._entries():
            self.assertLessEqual(entry["mean_volume"], -60)
            self.assertEqual(entry["result"]["background_had_audio"], key.startswith("a-"))

    def test_loop_has_no_black_gaps(self):
        for key, entry in self._entries():
            self.assertEqual(entry["black"], [])

    def test_no_part_files_left(self):
        self.assertEqual(sorted(p.name for p in self.out.glob("*.part*")), [])
        for key, entry in self._entries():
            self.assertTrue(Path(entry["result"]["output"]).exists())

    def test_vertical_source_same_in_crop_and_blur(self):
        crop = self.matrix["b-crop"]["result"]
        blur = self.matrix["b-blur"]["result"]
        self.assertTrue(crop and blur)
        self.assertEqual(_video_md5(self.ffmpeg, crop["output"]), _video_md5(self.ffmpeg, blur["output"]))

    def test_progress_callback_and_numbered_second_render(self):
        target = self.out / "repeat.mp4"
        first = shorts_core.render_video_short(self.audio, self.backgrounds["c"], target, 0, 15)
        values = []
        second = shorts_core.render_video_short(
            self.audio, self.backgrounds["c"], target, 0, 15, progress_cb=values.append
        )
        self.assertEqual(Path(first["output"]), target)
        self.assertEqual(Path(second["output"]), self.out / "repeat_1.mp4")
        self.assertGreaterEqual(len(values), 3)
        self.assertGreaterEqual(values[-1], 0.99)
        self.assertEqual(values, sorted(values))
        self.assertFalse(list(self.out.glob("repeat*.part*")))

    def test_cancel_before_start(self):
        event = threading.Event()
        event.set()
        target = self.out / "cancel_now.mp4"
        with self.assertRaises(shorts_core.RenderCancelled):
            shorts_core.render_video_short(self.audio, self.backgrounds["a"], target, 0, 20, cancel_event=event)
        self.assertFalse(list(self.out.glob("cancel_now*")))

    def test_cancel_during_render(self):
        event = threading.Event()
        target = self.out / "cancel_mid.mp4"

        def on_progress(value):
            if value > 0:
                event.set()

        with self.assertRaises(shorts_core.RenderCancelled):
            shorts_core.render_video_short(
                self.audio, self.backgrounds["a"], target, 0, 20, progress_cb=on_progress, cancel_event=event
            )
        self.assertFalse(list(self.out.glob("cancel_mid*")))


if __name__ == "__main__":
    unittest.main()
