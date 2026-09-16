import math
import shutil
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from PIL import Image

import shorts_core


def _option_value(cmd, option):
    idx = cmd.index(option)
    return cmd[idx + 1]


class SocialVideoCommandTests(unittest.TestCase):
    def test_render_command_forces_social_video_settings(self):
        with mock.patch.object(shorts_core, "ffmpeg_path", return_value="ffmpeg"):
            cmd = shorts_core.build_render_short_command(
                "audio.wav",
                "image.jpg",
                "out.mp4",
                0,
                45,
                motion_pattern="off",
                fade_sec=0,
                nvenc_available_fn=lambda: False,
            )

        self.assertIn("-c:v", cmd)
        self.assertEqual(_option_value(cmd, "-c:v"), "libx264")
        self.assertEqual(_option_value(cmd, "-pix_fmt"), "yuv420p")
        self.assertEqual(_option_value(cmd, "-profile:v"), "high")
        self.assertEqual(_option_value(cmd, "-level:v"), "4.1")
        self.assertEqual(_option_value(cmd, "-colorspace"), "bt709")
        self.assertEqual(_option_value(cmd, "-color_trc"), "bt709")
        self.assertEqual(_option_value(cmd, "-color_primaries"), "bt709")
        self.assertEqual(_option_value(cmd, "-color_range"), "tv")
        self.assertEqual(_option_value(cmd, "-r"), "30")
        self.assertEqual(_option_value(cmd, "-fps_mode:v"), "cfr")
        self.assertEqual(_option_value(cmd, "-c:a"), "aac")
        self.assertEqual(_option_value(cmd, "-profile:a"), "aac_low")
        self.assertEqual(_option_value(cmd, "-ar"), "48000")
        self.assertEqual(_option_value(cmd, "-ac"), "2")
        self.assertEqual(_option_value(cmd, "-movflags"), "+faststart")

        vf = _option_value(cmd, "-vf")
        self.assertIn("fps=fps=30", vf)
        self.assertIn("out_range=tv", vf)
        self.assertIn("out_color_matrix=bt709", vf)
        self.assertIn("format=yuv420p", vf)
        self.assertIn("setparams=range=tv", vf)
        self.assertIn("setpts=N/(30*TB)", vf)

    def test_nvenc_command_keeps_same_social_contract(self):
        with mock.patch.object(shorts_core, "ffmpeg_path", return_value="ffmpeg"):
            cmd = shorts_core.build_render_short_command(
                "audio.wav",
                "image.jpg",
                "out.mp4",
                0,
                45,
                use_nvenc=True,
                nvenc_available_fn=lambda: True,
            )

        self.assertEqual(_option_value(cmd, "-c:v"), "h264_nvenc")
        self.assertEqual(_option_value(cmd, "-pix_fmt"), "yuv420p")
        self.assertEqual(_option_value(cmd, "-colorspace"), "bt709")
        self.assertEqual(_option_value(cmd, "-color_range"), "tv")
        self.assertEqual(_option_value(cmd, "-fps_mode:v"), "cfr")

    def test_social_convert_command_uses_same_video_and_audio_contract(self):
        with mock.patch.object(shorts_core, "ffmpeg_path", return_value="ffmpeg"):
            cmd = shorts_core.build_social_convert_command("in.mp4", "out.mp4", has_audio=True)

        self.assertEqual(_option_value(cmd, "-c:v"), "libx264")
        self.assertEqual(_option_value(cmd, "-pix_fmt"), "yuv420p")
        self.assertEqual(_option_value(cmd, "-colorspace"), "bt709")
        self.assertEqual(_option_value(cmd, "-color_range"), "tv")
        self.assertEqual(_option_value(cmd, "-fps_mode:v"), "cfr")
        self.assertEqual(_option_value(cmd, "-c:a"), "aac")
        self.assertEqual(_option_value(cmd, "-ar"), "48000")
        self.assertEqual(_option_value(cmd, "-ac"), "2")
        self.assertEqual(_option_value(cmd, "-movflags"), "+faststart")

    def test_scan_pairs_regression_matches_numbered_audio_and_image(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            (folder / "01 Song.wav").write_bytes(b"")
            (folder / "01 Cover.jpg").write_bytes(b"")

            pairs = shorts_core.scan_pairs(folder)

        self.assertEqual(len(pairs), 1)
        self.assertTrue(pairs[0][1].endswith("01 Cover.jpg"))

    def test_batch_social_conversion_skips_existing_social_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            original = folder / "clip.mp4"
            original.write_bytes(b"")
            (folder / "clip_SOCIAL.mp4").write_bytes(b"")
            (folder / "clip_SOCIAL_2.mp4").write_bytes(b"")

            def fake_convert(path, use_nvenc=False):
                return {"input_path": str(path), "output_path": str(path).replace(".mp4", "_SOCIAL.mp4"), "validation": {"compatible": True}}

            with mock.patch.object(shorts_core, "convert_to_social_compatible", side_effect=fake_convert) as convert:
                results = shorts_core.batch_convert_to_social_compatible(folder)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["input_path"], str(original))
        convert.assert_called_once()


class SocialVideoValidationTests(unittest.TestCase):
    def _temp_mp4_path(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return Path(tmp.name)

    def test_validate_social_video_accepts_expected_probe(self):
        path = self._temp_mp4_path()
        probe = {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "45.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "profile": "High",
                    "level": 41,
                    "width": 1080,
                    "height": 1920,
                    "pix_fmt": "yuv420p",
                    "color_range": "tv",
                    "color_space": "bt709",
                    "color_transfer": "bt709",
                    "color_primaries": "bt709",
                    "field_order": "progressive",
                    "avg_frame_rate": "30/1",
                    "r_frame_rate": "30/1",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "profile": "LC",
                    "sample_rate": "48000",
                    "channels": 2,
                    "channel_layout": "stereo",
                },
            ],
        }

        with mock.patch.object(shorts_core, "_probe_media", return_value=probe):
            result = shorts_core.validate_social_video(path)

        self.assertTrue(result["compatible"])
        self.assertEqual(result["video_codec"], "h264")
        self.assertEqual(result["resolution"], "1080x1920")
        self.assertEqual(result["fps"], 30)
        self.assertEqual(result["pixel_format"], "yuv420p")
        self.assertEqual(result["color_space"], "bt709")
        self.assertEqual(result["color_range"], "tv")
        self.assertEqual(result["audio_codec"], "aac")
        self.assertEqual(result["sample_rate"], 48000)
        self.assertEqual(result["channels"], 2)
        self.assertEqual(result["duration"], 45.0)
        self.assertEqual(result["issues"], [])

    def test_validate_social_video_reports_old_yuvj_full_range_problem(self):
        path = self._temp_mp4_path()
        probe = {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "45.0"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "pix_fmt": "yuvj420p",
                    "color_range": "pc",
                    "color_space": "bt470bg",
                    "color_transfer": "bt470bg",
                    "color_primaries": "bt470bg",
                    "avg_frame_rate": "30000/1001",
                    "r_frame_rate": "30/1",
                },
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
            ],
        }

        with mock.patch.object(shorts_core, "_probe_media", return_value=probe):
            result = shorts_core.validate_social_video(path)

        self.assertFalse(result["compatible"])
        self.assertIn("Pixel format이 yuv420p가 아닙니다.", result["issues"])
        self.assertIn("Color range가 limited/tv가 아닙니다.", result["issues"])
        self.assertIn("Color space가 BT.709가 아닙니다.", result["issues"])
        self.assertIn("Frame rate가 CFR 30fps가 아닙니다.", result["issues"])


class SocialVideoIntegrationTests(unittest.TestCase):
    def test_render_short_outputs_probe_clean_social_mp4(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe are not available")

        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            image = folder / "source.jpg"
            audio = folder / "source.wav"
            output = folder / "out.mp4"

            Image.new("RGB", (640, 480), (220, 30, 70)).save(image, quality=95)
            with wave.open(str(audio), "w") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(44100)
                for n in range(44100 * 2):
                    sample = int(16000 * math.sin(2 * math.pi * 440 * n / 44100))
                    wav.writeframes(struct.pack("<h", sample))

            shorts_core.render_short(
                str(audio),
                str(image),
                str(output),
                0,
                2,
                mode="fill",
                zoom_pct=0,
                fade_sec=0,
                motion_pattern="off",
            )
            result = shorts_core.validate_social_video(output, min_duration=1.8, max_duration=2.2)

        self.assertTrue(result["compatible"], result["issues"])
        self.assertEqual(result["video_codec"], "h264")
        self.assertEqual(result["resolution"], "1080x1920")
        self.assertEqual(result["fps"], 30)
        self.assertEqual(result["pixel_format"], "yuv420p")
        self.assertEqual(result["color_range"], "tv")
        self.assertEqual(result["color_space"], "bt709")
        self.assertEqual(result["color_transfer"], "bt709")
        self.assertEqual(result["color_primaries"], "bt709")
        self.assertEqual(result["audio_codec"], "aac")
        self.assertEqual(result["sample_rate"], 48000)
        self.assertEqual(result["channels"], 2)


if __name__ == "__main__":
    unittest.main()
