from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None

try:
    import librosa
except Exception:
    librosa = None

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
SOCIAL_WIDTH = 1080
SOCIAL_HEIGHT = 1920
SOCIAL_FPS = 30
SOCIAL_COLOR = "bt709"
SOCIAL_RANGE = "tv"
SOCIAL_PIX_FMT = "yuv420p"
SOCIAL_AUDIO_RATE = 48000
SOCIAL_AUDIO_CHANNELS = 2
SOCIAL_AUDIO_BITRATE = "192k"


@dataclass
class HighlightResult:
    start: float
    end: float
    duration: float
    score: float
    bpm: float
    reason: str


def ffmpeg_path():
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_path():
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = Path(ffmpeg_path())
    candidate = ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    return str(candidate) if candidate.exists() else None


def _run(cmd):
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kw,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-5000:] or "FFmpeg 실행 오류")
    return p.stdout + p.stderr


def _require_librosa():
    if librosa is None:
        raise RuntimeError("librosa is required for audio analysis. Please install project requirements.")
    return librosa


def nvenc_available():
    try:
        p = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return "h264_nvenc" in (p.stdout + p.stderr)
    except Exception:
        return False


def decode_mono(audio_path, sr=22050):
    lb = _require_librosa()
    with tempfile.TemporaryDirectory(prefix="shortsmaker_") as td:
        wav = str(Path(td) / "audio.wav")
        _run(
            [
                ffmpeg_path(),
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                audio_path,
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sr),
                "-c:a",
                "pcm_s16le",
                wav,
            ]
        )
        y, _ = lb.load(wav, sr=sr, mono=True)
    return y, sr


def waveform_points(audio_path, points=1200):
    y, sr = decode_mono(audio_path, 22050)
    if len(y) == 0:
        return np.zeros(points), 0.0
    chunks = np.array_split(np.abs(y), points)
    vals = np.array([float(np.max(c)) if len(c) else 0.0 for c in chunks], dtype=float)
    m = vals.max() if vals.size else 1.0
    if m > 0:
        vals /= m
    return vals, len(y) / sr


def extract_preview_wav(audio_path, start, duration, out_path):
    _run(
        [
            ffmpeg_path(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            audio_path,
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            out_path,
        ]
    )
    return out_path


def analyze_top_highlights(audio_path, target_duration=45.0, top_n=3):
    lb = _require_librosa()
    target_duration = float(np.clip(target_duration, 30.0, 60.0))
    y, sr = decode_mono(audio_path, 22050)
    total = len(y) / sr
    if total <= target_duration + 2:
        return [
            HighlightResult(
                0.0,
                min(total, target_duration),
                min(total, target_duration),
                1.0,
                0.0,
                "짧은 곡 전체 사용",
            )
        ]

    hop = 512
    rms = lb.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    onset = lb.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    spectrum = np.abs(lb.stft(y, n_fft=2048, hop_length=hop))
    flux = np.sqrt(np.maximum(0.0, np.diff(spectrum, axis=1, prepend=spectrum[:, :1]) ** 2).mean(axis=0))

    def norm(v):
        v = np.asarray(v, float)
        lo, hi = np.percentile(v, 5), np.percentile(v, 95)
        return np.zeros_like(v) if hi <= lo + 1e-12 else np.clip((v - lo) / (hi - lo), 0, 1)

    rn, on, fn = norm(rms), norm(onset), norm(flux)
    times = lb.frames_to_time(np.arange(len(rn)), sr=sr, hop_length=hop)
    try:
        tempo, beats = lb.beat.beat_track(y=y, sr=sr, hop_length=hop)
        bpm = float(np.atleast_1d(tempo)[0])
        beat_times = lb.frames_to_time(beats, sr=sr, hop_length=hop)
    except Exception:
        bpm = 0.0
        beat_times = np.array([])

    max_start = total - target_duration
    margin = min(8.0, max(3.0, total * 0.035))
    step = 1.0 if total < 240 else 2.0
    starts = np.arange(margin, max(margin + 0.1, max_start - margin), step)
    if not len(starts):
        starts = np.arange(0, max_start + 0.1, step)
    med = float(np.median(rn))
    scored = []

    for st in starts:
        en = st + target_duration
        mask = (times >= st) & (times < en)
        if mask.sum() < 8:
            continue
        rr, oo, ff = rn[mask], on[mask], fn[mask]
        energy = float(np.mean(rr))
        p75 = float(np.percentile(rr, 75))
        rhythm = float(np.mean(oo))
        spectral = float(np.mean(ff))
        dynamic = float(np.percentile(rr, 90) - np.percentile(rr, 20))
        stability = max(0.0, 1.0 - float(np.std(rr)) * 1.65)
        hook = (0.58 * energy + 0.42 * p75) * (0.65 + 0.35 * stability)
        quiet = max(0.0, (med * 0.72) - energy) * 0.45
        pos = (st + target_duration / 2) / total
        pos_bonus = 0.045 * (1.0 - min(1.0, abs(pos - 0.58) / 0.58))
        edge_n = max(1, int(1.2 * sr / hop))
        edge_bonus = 0.035 * min(float(np.mean(rr[:edge_n])), float(np.mean(rr[-edge_n:])))
        score = 0.43 * hook + 0.22 * rhythm + 0.13 * spectral + 0.12 * dynamic + pos_bonus + edge_bonus - quiet
        scored.append((float(score), float(st)))

    scored.sort(reverse=True)
    picked = []
    sep = target_duration * 0.55

    for score, st in scored:
        if any(abs(st - p[1]) < sep for p in picked):
            continue
        if beat_times.size:
            near = beat_times[np.abs(beat_times - st) <= 1.35]
            if near.size:
                before = near[near <= st + 0.15]
                chosen = before[-1] if before.size else near[np.argmin(np.abs(near - st))]
                if 0 <= chosen <= total - target_duration:
                    st = float(chosen)
        st = max(0.0, min(st, total - target_duration))
        picked.append((score, st))
        if len(picked) >= top_n:
            break

    return [
        HighlightResult(
            round(st, 3),
            round(st + target_duration, 3),
            target_duration,
            round(score, 4),
            round(bpm, 1),
            f"TOP {i}",
        )
        for i, (score, st) in enumerate(picked, 1)
    ]


MOTION_PATTERNS = [
    "off",
    "emotional_random",
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left_to_right",
    "pan_right_to_left",
    "pan_top_to_bottom",
    "pan_bottom_to_top",
    "diagonal_move",
    "center_zoom_rotate",
    "chorus_zoom",
]

LEGACY_MOTION_ALIASES = {
    "zoom_in": "slow_zoom_in",
    "zoom_out": "slow_zoom_out",
    "pan_left": "pan_right_to_left",
    "pan_right": "pan_left_to_right",
    "gentle": "center_zoom_rotate",
}

INTENSITY_SCALE = {
    "weak": 0.72,
    "medium": 1.0,
    "strong": 1.35,
    "약": 0.72,
    "중": 1.0,
    "강": 1.35,
}

BEAT_AMPLITUDE = {
    "off": 0.0,
    "weak": 0.004,
    "medium": 0.008,
    "끔": 0.0,
    "약": 0.004,
    "중": 0.008,
}

SUBTITLE_POSITION_STYLE = {
    "top": {"Alignment": 8, "MarginV": 130},
    "center": {"Alignment": 5, "MarginV": 0},
    "bottom": {"Alignment": 2, "MarginV": 150},
    "safe_bottom": {"Alignment": 2, "MarginV": 230},
}

SUBTITLE_POSITION_ALIASES = {
    "상단": "top",
    "중앙": "center",
    "하단": "bottom",
    "하단 안전영역": "safe_bottom",
}

SUBTITLE_SIZE_STYLE = {
    "small": {"FontSize": 13, "Outline": 1.1, "Shadow": 0.5},
    "medium": {"FontSize": 15, "Outline": 1.35, "Shadow": 0.7},
    "large": {"FontSize": 18, "Outline": 1.7, "Shadow": 0.9},
}

SUBTITLE_SIZE_ALIASES = {
    "작게": "small",
    "보통": "medium",
    "크게": "large",
}

SUBTITLE_STYLE_PRESETS = {
    "emotional": {
        "FontName": "Malgun Gothic",
        "Bold": 0,
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H66000000",
        "BackColour": "&H99000000",
        "BorderStyle": 1,
    },
    "tiktok": {
        "FontName": "Malgun Gothic",
        "Bold": 1,
        "PrimaryColour": "&H00FFFFFF",
        "OutlineColour": "&H00000000",
        "BackColour": "&H99000000",
        "BorderStyle": 1,
    },
    "music": {
        "FontName": "Malgun Gothic",
        "Bold": 0,
        "PrimaryColour": "&H00F7EFE2",
        "OutlineColour": "&H6618120D",
        "BackColour": "&H99000000",
        "BorderStyle": 1,
    },
}

SUBTITLE_STYLE_ALIASES = {
    "감성형": "emotional",
    "틱톡형": "tiktok",
    "뮤직형": "music",
}

OVERLAY_ALIASES = {
    "없음": "none",
    "필름그레인": "film_grain",
    "먼지": "dust",
    "빛샘": "light_leak",
    "비": "rain",
    "눈": "snow",
    "보케": "bokeh",
}


def prepare_vertical_image(image_path, out_path, mode="fill", width=1080, height=1920):
    img = Image.open(image_path).convert("RGB")
    if mode == "blur":
        bg = img.copy()
        ratio = max(width / bg.width, height / bg.height)
        bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
        left = (bg.width - width) // 2
        top = (bg.height - height) // 2
        bg = bg.crop((left, top, left + width, top + height)).filter(ImageFilter.GaussianBlur(28))
        fg = img.copy()
        ratio = min(width / fg.width, height / fg.height)
        fg = fg.resize((max(1, int(fg.width * ratio)), max(1, int(fg.height * ratio))), Image.LANCZOS)
        x = (width - fg.width) // 2
        y = (height - fg.height) // 2
        bg.paste(fg, (x, y))
        out = bg
    else:
        ratio = max(width / img.width, height / img.height)
        img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
        left = (img.width - width) // 2
        top = (img.height - height) // 2
        out = img.crop((left, top, left + width, top + height))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, quality=95)
    return out_path


def _normalize_motion(value):
    value = LEGACY_MOTION_ALIASES.get(value, value)
    return value if value in MOTION_PATTERNS else "slow_zoom_in"


def _norm_choice(value, aliases, valid, default):
    value = aliases.get(value, value)
    return value if value in valid else default


def _beat_expr(beat_reactivity, transition_interval, fps):
    amp = BEAT_AMPLITUDE.get(beat_reactivity, 0.0)
    if amp <= 0:
        return ""
    beat_frames = max(8.0, float(transition_interval) * float(fps) / 2.0)
    return f"+{amp:.6f}*max(0,sin(2*PI*on/{beat_frames:.3f}))"


def _motion_expressions(motion_pattern, frames, fps, zoom_pct, motion_intensity, transition_interval, beat_reactivity):
    motion_pattern = _normalize_motion(motion_pattern)
    if motion_pattern == "off":
        return "1.0", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)", ""
    strength = INTENSITY_SCALE.get(motion_intensity, 1.0)
    zoom_pct = max(0.0, min(float(zoom_pct), 15.0)) * strength
    frame_span = max(1, int(frames) - 1)
    zmax = 1.0 + zoom_pct / 100.0
    pan_zmax = max(zmax, 1.055 + 0.025 * strength)
    beat = _beat_expr(beat_reactivity, transition_interval, fps)

    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"

    if motion_pattern == "emotional_random":
        segment = max(30.0, float(transition_interval) * float(fps))
        z_limit = max(zmax, 1.035 + 0.025 * strength)
        z = f"min(1.0+({z_limit - 1:.8f})*(0.38+0.62*(0.5+0.5*sin(2*PI*on/{segment:.3f})))" f"{beat},{z_limit:.5f})"
        x = f"(iw-iw/zoom)*(0.5+0.24*sin(2*PI*on/({segment:.3f}*2)))"
        y = f"(ih-ih/zoom)*(0.5+0.16*cos(2*PI*on/{segment:.3f}))"
        return z, x, y, ""
    if motion_pattern == "slow_zoom_out":
        z = f"max({zmax:.5f}-({zmax - 1:.8f}*on/{frame_span}){beat},1.0)"
        return z, center_x, center_y, ""
    if motion_pattern == "pan_left_to_right":
        z = f"{pan_zmax:.5f}{beat}"
        return z, f"(iw-iw/zoom)*(on/{frame_span})", center_y, ""
    if motion_pattern == "pan_right_to_left":
        z = f"{pan_zmax:.5f}{beat}"
        return z, f"(iw-iw/zoom)*(1-on/{frame_span})", center_y, ""
    if motion_pattern == "pan_top_to_bottom":
        z = f"{pan_zmax:.5f}{beat}"
        return z, center_x, f"(ih-ih/zoom)*(on/{frame_span})", ""
    if motion_pattern == "pan_bottom_to_top":
        z = f"{pan_zmax:.5f}{beat}"
        return z, center_x, f"(ih-ih/zoom)*(1-on/{frame_span})", ""
    if motion_pattern == "diagonal_move":
        z = f"{pan_zmax:.5f}{beat}"
        return z, f"(iw-iw/zoom)*(on/{frame_span})", f"(ih-ih/zoom)*(0.18+0.64*on/{frame_span})", ""
    if motion_pattern == "center_zoom_rotate":
        z = f"min(1.0+({zmax - 1:.8f}*on/{frame_span}){beat},{zmax:.5f})"
        rotate = f"rotate='0.010*sin(2*PI*t/{max(float(transition_interval), 3.0):.3f})':fillcolor=black"
        return z, center_x, center_y, rotate
    if motion_pattern == "chorus_zoom":
        a = frames * 0.32
        b = frames * 0.55
        bump = 0.018 * strength
        limit = zmax + bump
        z = (
            f"min(1.0+({zmax - 1:.8f}*on/{frame_span})"
            f"+{bump:.6f}*between(on,{a:.3f},{b:.3f})*sin((on-{a:.3f})/({b - a:.3f})*PI)"
            f"{beat},{limit:.5f})"
        )
        return z, center_x, center_y, ""

    z = f"min(1.0+({zmax - 1:.8f}*on/{frame_span}){beat},{zmax:.5f})"
    return z, center_x, center_y, ""


def _subtitle_force_style(subtitle_position="safe_bottom", subtitle_size="medium", subtitle_style="emotional"):
    position_key = _norm_choice(subtitle_position, SUBTITLE_POSITION_ALIASES, SUBTITLE_POSITION_STYLE, "safe_bottom")
    size_key = _norm_choice(subtitle_size, SUBTITLE_SIZE_ALIASES, SUBTITLE_SIZE_STYLE, "medium")
    style_key = _norm_choice(subtitle_style, SUBTITLE_STYLE_ALIASES, SUBTITLE_STYLE_PRESETS, "emotional")

    style = {}
    style.update(SUBTITLE_STYLE_PRESETS[style_key])
    style.update(SUBTITLE_SIZE_STYLE[size_key])
    style.update(SUBTITLE_POSITION_STYLE[position_key])
    style.update({"MarginL": 92, "MarginR": 92, "WrapStyle": 2, "Spacing": 0})
    return ",".join(f"{k}={v}" for k, v in style.items())


def _filter_path(path):
    return str(Path(path).resolve()).replace("\\", "/").replace("'", "\\'").replace(":", "\\:")


def _overlay_filters(overlay_effect):
    effect = OVERLAY_ALIASES.get(overlay_effect, overlay_effect)
    if effect == "film_grain":
        return ["noise=alls=4:allf=t+u"]
    if effect == "dust":
        return ["noise=alls=3:allf=t+u", "vignette=PI/7"]
    if effect == "light_leak":
        return ["colorchannelmixer=rr=1.04:gg=1.02:bb=.96", "eq=brightness=0.02:saturation=1.06"]
    if effect == "rain":
        return ["noise=alls=8:allf=t+u", "eq=contrast=1.02:brightness=-0.01:saturation=0.92"]
    if effect == "snow":
        return ["noise=alls=10:allf=t+u", "eq=brightness=0.03:saturation=0.95"]
    if effect == "bokeh":
        return ["gblur=sigma=0.45", "eq=saturation=1.12:contrast=1.03"]
    return []


def social_video_filter(vf, fps=SOCIAL_FPS, width=SOCIAL_WIDTH, height=SOCIAL_HEIGHT):
    fps = int(SOCIAL_FPS)
    width = int(SOCIAL_WIDTH)
    height = int(SOCIAL_HEIGHT)
    final_filters = [
        f"fps=fps={fps}:round=near",
        f"scale={width}:{height}:flags=lanczos:in_range=auto:out_range=tv:out_color_matrix=bt709",
        "setsar=1",
        "format=yuv420p",
        "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
        f"setpts=N/({fps}*TB)",
    ]
    return f"{vf}," + ",".join(final_filters)


def social_audio_filter(af="anull"):
    af = af or "anull"
    return ",".join(
        [
            af,
            f"aresample={SOCIAL_AUDIO_RATE}",
            f"aformat=sample_rates={SOCIAL_AUDIO_RATE}:channel_layouts=stereo",
        ]
    )


def social_video_encode_args(use_nvenc=False, fps=SOCIAL_FPS, nvenc_available_fn=None):
    fps = int(SOCIAL_FPS)
    checker = nvenc_available_fn or nvenc_available
    use_hw = False
    if use_nvenc:
        try:
            use_hw = bool(checker())
        except Exception:
            use_hw = False

    common = [
        "-pix_fmt",
        SOCIAL_PIX_FMT,
        "-profile:v",
        "high",
        "-level:v",
        "4.1",
        "-colorspace",
        SOCIAL_COLOR,
        "-color_primaries",
        SOCIAL_COLOR,
        "-color_trc",
        SOCIAL_COLOR,
        "-color_range",
        SOCIAL_RANGE,
        "-r",
        str(fps),
        "-fps_mode:v",
        "cfr",
    ]
    if use_hw:
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p5",
            "-cq",
            "19",
            "-b:v",
            "8M",
            "-maxrate",
            "12M",
            "-bufsize",
            "16M",
        ] + common
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "18"] + common


def social_audio_encode_args():
    return [
        "-c:a",
        "aac",
        "-profile:a",
        "aac_low",
        "-b:a",
        SOCIAL_AUDIO_BITRATE,
        "-ar",
        str(SOCIAL_AUDIO_RATE),
        "-ac",
        str(SOCIAL_AUDIO_CHANNELS),
    ]


def social_mp4_output_args():
    return [
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-movflags",
        "+faststart",
        "-avoid_negative_ts",
        "make_zero",
        "-shortest",
    ]


def build_render_short_command(
    audio_path,
    image_path,
    output_path,
    start,
    duration,
    mode="fill",
    zoom_pct=6.0,
    fade_sec=0.5,
    fps=SOCIAL_FPS,
    width=SOCIAL_WIDTH,
    height=SOCIAL_HEIGHT,
    use_nvenc=False,
    motion_pattern="slow_zoom_in",
    subtitle_path="",
    subtitle_position="safe_bottom",
    subtitle_size="medium",
    subtitle_style="emotional",
    motion_intensity="medium",
    transition_interval=5,
    beat_reactivity="off",
    overlay_effect="none",
    nvenc_available_fn=None,
):
    fps = int(SOCIAL_FPS)
    width = int(SOCIAL_WIDTH)
    height = int(SOCIAL_HEIGHT)
    duration = max(1.0, float(duration))
    motion_pattern = _normalize_motion(motion_pattern)
    motion_off = motion_pattern == "off"
    fade_sec = max(0.0, min(float(fade_sec), duration / 4))
    if motion_off:
        fade_sec = 0.0
        beat_reactivity = "off"
        overlay_effect = "none"
    frames = max(1, int(duration * fps))
    transition_interval = max(3.0, float(transition_interval or 5))
    z, x, y, rotate_filter = _motion_expressions(
        motion_pattern,
        frames,
        fps,
        zoom_pct,
        motion_intensity,
        transition_interval,
        beat_reactivity,
    )

    if mode == "blur":
        vf = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=30:5[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"
        )
    else:
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"
        )

    if rotate_filter:
        vf += f",{rotate_filter}"

    for overlay_filter in _overlay_filters(overlay_effect):
        vf += f",{overlay_filter}"

    if subtitle_path and Path(subtitle_path).exists():
        sp = _filter_path(subtitle_path)
        style = _subtitle_force_style(subtitle_position, subtitle_size, subtitle_style)
        vf += f",subtitles='{sp}':force_style='{style}'"

    if fade_sec > 0:
        fo = max(0.0, duration - fade_sec)
        vf += f",fade=t=in:st=0:d={fade_sec},fade=t=out:st={fo}:d={fade_sec}"
        af = f"afade=t=in:st=0:d={fade_sec},afade=t=out:st={fo}:d={fade_sec}"
    else:
        af = "anull"

    vf = social_video_filter(vf, fps, width, height)
    af = social_audio_filter(af)

    cmd = [
        ffmpeg_path(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-i",
        str(image_path),
        "-ss",
        f"{float(start):.3f}",
        "-i",
        str(audio_path),
    ]
    if mode == "blur":
        cmd += ["-filter_complex", vf + "[v]", "-map", "[v]", "-map", "1:a:0"]
    else:
        cmd += ["-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-af", af, "-t", f"{duration:.3f}"]
    cmd += social_video_encode_args(use_nvenc=use_nvenc, fps=fps, nvenc_available_fn=nvenc_available_fn)
    cmd += social_audio_encode_args()
    cmd += social_mp4_output_args()
    cmd += [str(output_path)]
    return cmd


def render_short(
    audio_path,
    image_path,
    output_path,
    start,
    duration,
    mode="fill",
    zoom_pct=6.0,
    fade_sec=0.5,
    fps=30,
    width=1080,
    height=1920,
    use_nvenc=False,
    motion_pattern="slow_zoom_in",
    subtitle_path="",
    subtitle_position="safe_bottom",
    subtitle_size="medium",
    subtitle_style="emotional",
    motion_intensity="medium",
    transition_interval=5,
    beat_reactivity="off",
    overlay_effect="none",
):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cmd = build_render_short_command(
        audio_path,
        image_path,
        output_path,
        start,
        duration,
        mode,
        zoom_pct,
        fade_sec,
        fps,
        width,
        height,
        use_nvenc,
        motion_pattern,
        subtitle_path,
        subtitle_position,
        subtitle_size,
        subtitle_style,
        motion_intensity,
        transition_interval,
        beat_reactivity,
        overlay_effect,
    )
    _run(cmd)
    return output_path


def _run_capture(cmd):
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kw,
    )


def _parse_rate(value):
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        return float(Fraction(str(value)))
    except Exception:
        try:
            return float(value)
        except Exception:
            return None


def _near(value, target, tolerance=0.01):
    return value is not None and abs(float(value) - float(target)) <= tolerance


def _probe_with_ffprobe(path):
    probe = ffprobe_path()
    if not probe:
        return None
    p = _run_capture(
        [
            probe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        return json.loads(p.stdout)
    except Exception:
        return None


def _probe_with_ffmpeg(path):
    p = _run_capture([ffmpeg_path(), "-hide_banner", "-i", str(path)])
    text = (p.stderr or "") + "\n" + (p.stdout or "")
    if not text.strip():
        return None

    format_name = ""
    if "Input #0, mov,mp4,m4a,3gp,3g2,mj2" in text:
        format_name = "mov,mp4,m4a,3gp,3g2,mj2"

    duration = None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    streams = []
    for raw in text.splitlines():
        line = raw.strip()
        if " Video: " in line:
            stream = {"codec_type": "video"}
            m = re.search(r"Video:\s*([^,\s]+)", line)
            if m:
                stream["codec_name"] = m.group(1).lower()
            m = re.search(r"Video:\s*[^(,\s]+(?:\s*\(([^)]*)\))?", line)
            if m and m.group(1):
                stream["profile"] = m.group(1)
            m = re.search(r"(\d{2,5})x(\d{2,5})", line)
            if m:
                stream["width"] = int(m.group(1))
                stream["height"] = int(m.group(2))
            m = re.search(r",\s*([a-z0-9_]+)(?:\(([^)]*)\))?,\s*\d{2,5}x\d{2,5}", line, re.I)
            if m:
                stream["pix_fmt"] = m.group(1)
                tags = [x.strip() for x in (m.group(2) or "").split(",") if x.strip()]
                if tags:
                    if tags[0] in {"tv", "pc"}:
                        stream["color_range"] = tags[0]
                        tags = tags[1:]
                    for tag in tags:
                        if tag == "bt709":
                            stream["color_space"] = "bt709"
                            stream["color_transfer"] = "bt709"
                            stream["color_primaries"] = "bt709"
            m = re.search(r"(\d+(?:\.\d+)?)\s*fps", line)
            if m:
                stream["avg_frame_rate"] = f"{m.group(1)}/1"
                stream["r_frame_rate"] = f"{m.group(1)}/1"
            if duration is not None:
                stream["duration"] = str(duration)
            streams.append(stream)
        elif " Audio: " in line:
            stream = {"codec_type": "audio"}
            m = re.search(r"Audio:\s*([^,\s]+)", line)
            if m:
                stream["codec_name"] = m.group(1).lower()
            m = re.search(r"Audio:\s*[^(,\s]+(?:\s*\(([^)]*)\))?", line)
            if m and m.group(1):
                stream["profile"] = m.group(1)
            m = re.search(r"(\d+)\s*Hz", line)
            if m:
                stream["sample_rate"] = m.group(1)
            if re.search(r"\bstereo\b", line, re.I):
                stream["channels"] = 2
                stream["channel_layout"] = "stereo"
            elif re.search(r"\bmono\b", line, re.I):
                stream["channels"] = 1
                stream["channel_layout"] = "mono"
            if duration is not None:
                stream["duration"] = str(duration)
            streams.append(stream)

    return {"format": {"format_name": format_name, "duration": str(duration or "")}, "streams": streams}


def _probe_media(path):
    return _probe_with_ffprobe(path) or _probe_with_ffmpeg(path)


def validate_social_video(path, min_duration=30.0, max_duration=60.0):
    result = {
        "compatible": False,
        "container": "",
        "video_codec": "",
        "video_profile": "",
        "video_level": None,
        "resolution": "",
        "aspect_ratio": "",
        "fps": None,
        "avg_frame_rate": "",
        "r_frame_rate": "",
        "fps_mode": "",
        "pixel_format": "",
        "color_space": "",
        "color_transfer": "",
        "color_primaries": "",
        "color_range": "",
        "field_order": "",
        "audio_codec": "",
        "audio_profile": "",
        "sample_rate": None,
        "channels": None,
        "channel_layout": "",
        "duration": None,
        "issues": [],
    }

    media_path = Path(path)
    if not media_path.exists():
        result["issues"].append("파일이 존재하지 않습니다.")
        return result

    probe = _probe_media(media_path)
    if not probe:
        result["issues"].append("미디어 정보를 확인할 수 없습니다.")
        return result

    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

    format_name = (fmt.get("format_name") or "").lower()
    result["container"] = "mp4" if "mp4" in format_name or "mov" in format_name else format_name
    if result["container"] != "mp4":
        result["issues"].append("MP4 컨테이너가 아닙니다.")

    duration = fmt.get("duration") or video.get("duration") or audio.get("duration")
    try:
        result["duration"] = round(float(duration), 3)
    except Exception:
        result["duration"] = None
    if result["duration"] is None:
        result["issues"].append("Duration을 확인할 수 없습니다.")
    elif not (float(min_duration) <= result["duration"] <= float(max_duration)):
        result["issues"].append(f"Duration이 {min_duration:g}~{max_duration:g}초 범위가 아닙니다.")

    if not video:
        result["issues"].append("비디오 스트림이 없습니다.")
    else:
        result["video_codec"] = (video.get("codec_name") or "").lower()
        result["video_profile"] = video.get("profile") or ""
        result["video_level"] = video.get("level")
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        result["resolution"] = f"{width}x{height}" if width and height else ""
        result["aspect_ratio"] = "9:16" if width * 16 == height * 9 and width else ""
        result["pixel_format"] = video.get("pix_fmt") or ""
        result["color_space"] = video.get("color_space") or ""
        result["color_transfer"] = video.get("color_transfer") or ""
        result["color_primaries"] = video.get("color_primaries") or ""
        result["color_range"] = video.get("color_range") or ""
        result["field_order"] = video.get("field_order") or ""
        result["avg_frame_rate"] = video.get("avg_frame_rate") or ""
        result["r_frame_rate"] = video.get("r_frame_rate") or ""
        avg_fps = _parse_rate(result["avg_frame_rate"])
        r_fps = _parse_rate(result["r_frame_rate"])
        result["fps"] = int(round(avg_fps)) if _near(avg_fps, round(avg_fps or 0)) else avg_fps
        is_cfr_30 = _near(avg_fps, SOCIAL_FPS) and (r_fps is None or _near(r_fps, SOCIAL_FPS))
        result["fps_mode"] = "cfr" if is_cfr_30 else "unknown"

        if result["video_codec"] != "h264":
            result["issues"].append("Video codec이 H.264가 아닙니다.")
        if width != SOCIAL_WIDTH or height != SOCIAL_HEIGHT:
            result["issues"].append("Resolution이 1080x1920이 아닙니다.")
        if result["aspect_ratio"] != "9:16":
            result["issues"].append("Aspect ratio가 9:16이 아닙니다.")
        if not is_cfr_30:
            result["issues"].append("Frame rate가 CFR 30fps가 아닙니다.")
        if result["pixel_format"] != SOCIAL_PIX_FMT:
            result["issues"].append("Pixel format이 yuv420p가 아닙니다.")
        if result["color_space"] != SOCIAL_COLOR:
            result["issues"].append("Color space가 BT.709가 아닙니다.")
        if result["color_transfer"] != SOCIAL_COLOR:
            result["issues"].append("Color transfer가 BT.709가 아닙니다.")
        if result["color_primaries"] != SOCIAL_COLOR:
            result["issues"].append("Color primaries가 BT.709가 아닙니다.")
        if result["color_range"] != SOCIAL_RANGE:
            result["issues"].append("Color range가 limited/tv가 아닙니다.")
        if result["field_order"] and result["field_order"] != "progressive":
            result["issues"].append("Progressive 영상이 아닙니다.")
        if result["video_profile"] and result["video_profile"].lower() != "high":
            result["issues"].append("H.264 profile이 High가 아닙니다.")
        if result["video_level"] not in (None, 41, "41"):
            result["issues"].append("H.264 level이 4.1이 아닙니다.")

    if not audio:
        result["issues"].append("오디오 스트림이 없습니다.")
    else:
        result["audio_codec"] = (audio.get("codec_name") or "").lower()
        result["audio_profile"] = audio.get("profile") or ""
        try:
            result["sample_rate"] = int(audio.get("sample_rate") or 0)
        except Exception:
            result["sample_rate"] = None
        try:
            result["channels"] = int(audio.get("channels") or 0)
        except Exception:
            result["channels"] = None
        result["channel_layout"] = audio.get("channel_layout") or ""

        if result["audio_codec"] != "aac":
            result["issues"].append("Audio codec이 AAC가 아닙니다.")
        if result["audio_profile"] and "LC" not in result["audio_profile"].upper():
            result["issues"].append("AAC-LC 오디오가 아닙니다.")
        if result["sample_rate"] != SOCIAL_AUDIO_RATE:
            result["issues"].append("Audio sample rate가 48000Hz가 아닙니다.")
        if result["channels"] != SOCIAL_AUDIO_CHANNELS:
            result["issues"].append("Audio channel이 stereo(2ch)가 아닙니다.")

    result["compatible"] = not result["issues"]
    return result


def _has_audio_stream(path):
    probe = _probe_media(path)
    if not probe:
        return True
    return any(s.get("codec_type") == "audio" for s in probe.get("streams") or [])


def _is_social_mp4(path):
    p = Path(path)
    return p.suffix.lower() == ".mp4" and re.search(r"_SOCIAL(?:_\d+)?$", p.stem, re.I) is not None


def _unique_existing_safe_path(path):
    out = Path(path)
    if not out.exists():
        return out
    n = 2
    while True:
        candidate = out.with_name(f"{out.stem}_{n}{out.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _default_social_output_path(input_path):
    src = Path(input_path)
    return src.with_name(f"{src.stem}_SOCIAL.mp4")


def build_social_convert_command(input_path, output_path, use_nvenc=False, has_audio=True, nvenc_available_fn=None):
    vf = (
        f"scale={SOCIAL_WIDTH}:{SOCIAL_HEIGHT}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={SOCIAL_WIDTH}:{SOCIAL_HEIGHT}"
    )
    vf = social_video_filter(vf, SOCIAL_FPS, SOCIAL_WIDTH, SOCIAL_HEIGHT)

    cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(input_path)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={SOCIAL_AUDIO_RATE}"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0"]
    cmd += ["-vf", vf, "-af", social_audio_filter("anull")]
    cmd += social_video_encode_args(use_nvenc=use_nvenc, fps=SOCIAL_FPS, nvenc_available_fn=nvenc_available_fn)
    cmd += social_audio_encode_args()
    cmd += social_mp4_output_args()
    cmd += [str(output_path)]
    return cmd


def convert_to_social_compatible(input_path, output_path=None, use_nvenc=False, overwrite=False):
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(str(src))
    out = Path(output_path) if output_path else _default_social_output_path(src)
    if out.resolve() == src.resolve():
        raise ValueError("Output path must not overwrite the original MP4.")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        out = _unique_existing_safe_path(out)
    has_audio = _has_audio_stream(src)
    cmd = build_social_convert_command(src, out, use_nvenc=use_nvenc, has_audio=has_audio)
    _run(cmd)
    validation = validate_social_video(out)
    return {"input_path": str(src), "output_path": str(out), "validation": validation}


def batch_convert_to_social_compatible(folder, use_nvenc=False):
    base = Path(folder)
    results = []
    for src in sorted(base.glob("*.mp4")):
        if _is_social_mp4(src):
            continue
        try:
            results.append(convert_to_social_compatible(src, use_nvenc=use_nvenc))
        except Exception as e:
            results.append(
                {
                    "input_path": str(src),
                    "output_path": "",
                    "validation": {"compatible": False, "issues": [str(e)]},
                    "error": str(e),
                }
            )
    return results


def save_video_thumbnail(video_path, out_path=None, at_sec=0.5):
    video = Path(video_path)
    if out_path is None:
        out_path = video.with_name(f"{video.stem}_thumb.jpg")
    out_path = Path(out_path)
    positions = []
    for pos in (at_sec, 0.35, 0.0):
        pos = max(0.0, float(pos))
        if pos not in positions:
            positions.append(pos)

    last_error = None
    for pos in positions:
        try:
            _run(
                [
                    ffmpeg_path(),
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{pos:.3f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    "-pix_fmt",
                    "yuvj420p",
                    str(out_path),
                ]
            )
            if out_path.exists() and out_path.stat().st_size > 0:
                return str(out_path)
        except Exception as e:
            last_error = e
        if out_path.exists():
            out_path.unlink(missing_ok=True)
    if last_error:
        raise RuntimeError(f"Thumbnail save failed: {last_error}")
    raise RuntimeError("Thumbnail save failed: no frame was written")


def _stem(p):
    return re.sub(r"\s+", " ", p.stem.lower().strip())


def _num(p):
    m = re.match(r"^\s*(\d{1,4})", p.stem)
    return (m.group(1).lstrip("0") or "0") if m else None


def scan_pairs(folder):
    base = Path(folder)
    audios = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    images = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    bystem = {_stem(p): p for p in images}
    bynum = {}
    for p in images:
        n = _num(p)
        if n is not None and n not in bynum:
            bynum[n] = p
    out = []
    for a in sorted(audios):
        img = bystem.get(_stem(a))
        match_type = "동일 파일명"
        if img is None:
            n = _num(a)
            if n is not None:
                img = bynum.get(n)
                if img is not None:
                    match_type = "앞번호 매칭"
        out.append((str(a), str(img) if img else "", match_type if img else "이미지 없음"))
    return out


def make_metadata(track_name, channel_name, template_name="감성형"):
    title_base = Path(track_name).stem
    if template_name == "일본 ChillRap":
        title = f"{title_base} | Tokyo ChillRap #Shorts"
        desc = (
            f"{title_base}\n\n"
            f"Tokyo night mood · ChillRap · Love Story\n"
            f"채널 {channel_name}\n\n"
            "#TokyoChillRap #ChillRap #Shorts"
        )
        tags = "#TokyoChillRap #ChillRap #JapanMusic #Shorts"
    elif template_name == "시니어 발라드":
        title = f"{title_base} | 추억의 발라드 #Shorts"
        desc = (
            f"{title_base}\n\n"
            f"추억을 깨우는 감성 발라드입니다.\n"
            f"채널 {channel_name}\n\n"
            "#발라드 #7080 #추억의팝송 #Shorts"
        )
        tags = "#발라드 #7080 #추억의팝송 #OldPop #Shorts"
    else:
        title = f"{title_base} | 감성 음악 #Shorts"
        desc = (
            f"{title_base}\n\n"
            f"잠시 머물다 가는 감성 음악.\n"
            f"채널 {channel_name}\n\n"
            "#감성음악 #플레이리스트 #Shorts"
        )
        tags = "#감성음악 #플레이리스트 #MusicShorts #Shorts"
    return {"title": title, "description": desc, "hashtags": tags}


def save_metadata_txt(output_dir, base_name, metadata):
    p = Path(output_dir) / f"{base_name}_업로드정보.txt"
    text = (
        f"제목\n{metadata['title']}\n\n"
        f"설명\n{metadata['description']}\n\n"
        f"해시태그\n{metadata['hashtags']}\n"
    )
    p.write_text(text, encoding="utf-8")
    return str(p)


def zip_outputs(output_dir, zip_path=None):
    out = Path(output_dir)
    if zip_path is None:
        zip_path = str(out.parent / f"{out.name}_Shorts_Package.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in out.rglob("*"):
            if p.is_file() and p.resolve() != Path(zip_path).resolve():
                z.write(p, p.relative_to(out))
    return zip_path


# --- video background (v0.7.0) ---

import threading as _threading
from collections import deque as _deque
from queue import Empty as _QueueEmpty
from queue import Queue as _Queue

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
VIDEO_FIT_MODES = ("crop", "blur")
VIDEO_SHORT_MIN_DURATION = 15.0
VIDEO_SHORT_MAX_DURATION = 60.0


class RenderCancelled(Exception):
    """Raised when a render is cancelled through cancel_event."""


def probe_background_video(video_path):
    """Return width/height/duration/fps/has_audio of a background clip.

    An audio track in the clip is not an error: it is reported through
    has_audio so the caller can warn, and it is never mapped into output.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"배경 영상 파일이 없습니다: {path}")
    probe = _probe_media(path)
    streams = (probe or {}).get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise ValueError(f"배경 영상에 영상 스트림이 없습니다: {path.name}")

    fmt = (probe or {}).get("format") or {}
    duration = None
    for raw in (fmt.get("duration"), video.get("duration")):
        try:
            duration = float(raw)
            break
        except (TypeError, ValueError):
            continue
    if duration is None or duration < 1.0:
        raise ValueError(f"배경 영상 길이가 1초 미만이거나 확인할 수 없습니다: {path.name}")

    fps = _parse_rate(video.get("avg_frame_rate")) or _parse_rate(video.get("r_frame_rate"))
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration": round(duration, 3),
        "fps": round(fps, 3) if fps else None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def _check_video_short_args(start, duration, fit_mode, video_offset):
    if fit_mode not in VIDEO_FIT_MODES:
        raise ValueError(f"fit_mode는 {', '.join(VIDEO_FIT_MODES)} 중 하나여야 합니다: {fit_mode!r}")
    duration = float(duration)
    if not (VIDEO_SHORT_MIN_DURATION <= duration <= VIDEO_SHORT_MAX_DURATION):
        raise ValueError(
            f"duration은 {VIDEO_SHORT_MIN_DURATION:g}~{VIDEO_SHORT_MAX_DURATION:g}초여야 합니다: {duration:g}"
        )
    video_offset = float(video_offset)
    if video_offset < 0:
        raise ValueError(f"video_offset은 0 이상이어야 합니다: {video_offset:g}")
    start = float(start)
    if start < 0:
        raise ValueError(f"start는 0 이상이어야 합니다: {start:g}")
    return start, duration, video_offset


def build_render_video_short_command(
    audio_path,
    video_path,
    output_path,
    start,
    duration,
    fit_mode="crop",
    video_offset=0.0,
    fade_sec=0.5,
    subtitle_path="",
    subtitle_position="safe_bottom",
    subtitle_size="medium",
    subtitle_style="emotional",
    use_nvenc=False,
    nvenc_available_fn=None,
):
    """FFmpeg command: looping silent background clip + audio highlight -> 9:16 short.

    Only the background video stream (0:v:0, via [v]) and the music track
    (1:a:0) are mapped; any audio inside the background clip is ignored.
    """
    start, duration, video_offset = _check_video_short_args(start, duration, fit_mode, video_offset)
    width = int(SOCIAL_WIDTH)
    height = int(SOCIAL_HEIGHT)
    fade_sec = max(0.0, min(float(fade_sec), duration / 4))

    if fit_mode == "blur":
        graph = (
            f"[0:v:0]split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=30:5[bg];"
            f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    else:
        graph = (
            f"[0:v:0]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )

    if subtitle_path and Path(subtitle_path).exists():
        sp = _filter_path(subtitle_path)
        style = _subtitle_force_style(subtitle_position, subtitle_size, subtitle_style)
        graph += f",subtitles='{sp}':force_style='{style}'"

    if fade_sec > 0:
        fo = max(0.0, duration - fade_sec)
        graph += f",fade=t=in:st=0:d={fade_sec},fade=t=out:st={fo}:d={fade_sec}"
        af = f"afade=t=in:st=0:d={fade_sec},afade=t=out:st={fo}:d={fade_sec}"
    else:
        af = "anull"

    graph = social_video_filter(graph, SOCIAL_FPS, width, height) + "[v]"
    af = social_audio_filter(af)

    cmd = [
        ffmpeg_path(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stream_loop",
        "-1",
        "-ss",
        f"{video_offset:.3f}",
        "-i",
        str(video_path),
        "-ss",
        f"{start:.3f}",
        "-i",
        str(audio_path),
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-map",
        "1:a:0",
        "-af",
        af,
        "-t",
        f"{duration:.3f}",
    ]
    cmd += social_video_encode_args(use_nvenc=use_nvenc, fps=SOCIAL_FPS, nvenc_available_fn=nvenc_available_fn)
    cmd += social_audio_encode_args()
    cmd += social_mp4_output_args()
    cmd += [str(output_path)]
    return cmd


def _numbered_output_path(path):
    """path if free, else path_1, path_2, ... (never overwrites)."""
    out = Path(path)
    if not out.exists():
        return out
    n = 1
    while True:
        candidate = out.with_name(f"{out.stem}_{n}{out.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _part_path(final_path):
    p = Path(final_path)
    return p.with_name(f"{p.stem}.part{p.suffix or '.mp4'}")


def _remove_quietly(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def _progress_seconds(key, value):
    if key not in ("out_time_us", "out_time_ms") or value in ("", "N/A"):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    # FFmpeg writes both out_time_us and out_time_ms in microseconds
    # (out_time_ms is a historical misnomer), so both are divided by 1e6.
    return number / 1_000_000


def _pump_lines(stream, sink):
    try:
        for line in iter(stream.readline, ""):
            sink(line)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def render_video_short(
    audio_path,
    video_path,
    output_path,
    start,
    duration,
    fit_mode="crop",
    video_offset=0.0,
    fade_sec=0.5,
    subtitle_path="",
    subtitle_position="safe_bottom",
    subtitle_size="medium",
    subtitle_style="emotional",
    use_nvenc=False,
    nvenc_available_fn=None,
    progress_cb=None,
    cancel_event=None,
):
    """Render a video-background short, validate it, and return a result dict.

    Progress is reported through progress_cb(fraction 0.0~1.0). Setting
    cancel_event stops FFmpeg, removes the partial file and raises
    RenderCancelled. The output never overwrites an existing file.
    """
    start, duration, video_offset = _check_video_short_args(start, duration, fit_mode, video_offset)
    audio = Path(audio_path)
    video = Path(video_path)
    if not audio.exists():
        raise FileNotFoundError(f"음원 파일이 없습니다: {audio}")

    requested = Path(output_path)
    inputs = {audio.resolve(), video.resolve()}
    if requested.resolve() in inputs:
        raise ValueError("출력 경로가 입력 파일과 같습니다. 원본을 덮어쓸 수 없습니다.")

    background = probe_background_video(video)

    if cancel_event is not None and cancel_event.is_set():
        raise RenderCancelled("렌더가 취소되었습니다.")

    requested.parent.mkdir(parents=True, exist_ok=True)
    final = _numbered_output_path(requested)
    part = _part_path(final)
    if part.resolve() in inputs:
        raise ValueError("임시 출력 경로가 입력 파일과 같습니다.")

    cmd = build_render_video_short_command(
        audio,
        video,
        part,
        start,
        duration,
        fit_mode=fit_mode,
        video_offset=video_offset,
        fade_sec=fade_sec,
        subtitle_path=subtitle_path,
        subtitle_position=subtitle_position,
        subtitle_size=subtitle_size,
        subtitle_style=subtitle_style,
        use_nvenc=use_nvenc,
        nvenc_available_fn=nvenc_available_fn,
    )
    cmd = cmd[:-1] + ["-progress", "pipe:1", "-nostats"] + cmd[-1:]

    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW

    def report(value):
        if progress_cb is not None:
            progress_cb(max(0.0, min(1.0, float(value))))

    stderr_tail = _deque(maxlen=200)
    stdout_lines = _Queue()
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kw,
    )
    readers = [
        _threading.Thread(target=_pump_lines, args=(proc.stderr, stderr_tail.append), daemon=True),
        _threading.Thread(target=_pump_lines, args=(proc.stdout, stdout_lines.put), daemon=True),
    ]
    for reader in readers:
        reader.start()

    succeeded = False
    try:
        report(0.0)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                proc.wait()
                raise RenderCancelled("렌더가 취소되었습니다.")
            try:
                line = stdout_lines.get(timeout=0.1)
            except _QueueEmpty:
                if proc.poll() is not None and not readers[1].is_alive() and stdout_lines.empty():
                    break
                continue
            key, _, value = line.strip().partition("=")
            seconds = _progress_seconds(key, value.strip())
            if seconds is not None:
                report(min(seconds / duration, 0.99))

        proc.wait()
        for reader in readers:
            reader.join(timeout=5)
        if proc.returncode != 0:
            tail = "".join(stderr_tail)[-5000:]
            raise RuntimeError(tail or f"FFmpeg 실행 오류 (code {proc.returncode})")

        validation = validate_social_video(part, min_duration=duration - 0.5, max_duration=duration + 0.5)
        if not validation["compatible"]:
            err = RuntimeError("SNS 호환 검증 실패: " + "; ".join(validation["issues"]))
            err.issues = list(validation["issues"])
            err.validation = validation
            raise err

        if final.exists():
            final = _numbered_output_path(final)
        os.replace(part, final)
        succeeded = True
        report(1.0)
        return {
            "output": str(final),
            "duration": validation["duration"],
            "background_had_audio": bool(background["has_audio"]),
            "validation": validation,
        }
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for reader in readers:
            reader.join(timeout=5)
        if not succeeded:
            _remove_quietly(part)


# --- headless helpers (v0.7.1) ---


def probe_audio_duration(audio_path):
    """Return the audio length in seconds (ffprobe, no decoding)."""
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"음원 파일이 없습니다: {path}")
    probe = _probe_media(path)
    streams = (probe or {}).get("streams") or []
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not audio:
        raise ValueError(f"음원에 오디오 스트림이 없습니다: {path.name}")
    fmt = (probe or {}).get("format") or {}
    for raw in (fmt.get("duration"), audio.get("duration")):
        try:
            duration = float(raw)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            return round(duration, 3)
    raise ValueError(f"음원 길이를 확인할 수 없습니다: {path.name}")


def nvenc_available_no_window():
    """Same check as nvenc_available, without flashing a console on Windows."""
    try:
        p = _run_capture([ffmpeg_path(), "-hide_banner", "-encoders"])
        return "h264_nvenc" in ((p.stdout or "") + (p.stderr or ""))
    except Exception:
        return False
