from __future__ import annotations

import os
import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import librosa
import numpy as np
from PIL import Image, ImageFilter

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass
class HighlightResult:
    start: float
    end: float
    duration: float
    score: float
    bpm: float
    reason: str


def ffmpeg_path():
    return imageio_ffmpeg.get_ffmpeg_exe()


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
        y, _ = librosa.load(wav, sr=sr, mono=True)
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
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    spectrum = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    flux = np.sqrt(np.maximum(0.0, np.diff(spectrum, axis=1, prepend=spectrum[:, :1]) ** 2).mean(axis=0))

    def norm(v):
        v = np.asarray(v, float)
        lo, hi = np.percentile(v, 5), np.percentile(v, 95)
        return np.zeros_like(v) if hi <= lo + 1e-12 else np.clip((v - lo) / (hi - lo), 0, 1)

    rn, on, fn = norm(rms), norm(onset), norm(flux)
    times = librosa.frames_to_time(np.arange(len(rn)), sr=sr, hop_length=hop)
    try:
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop)
        bpm = float(np.atleast_1d(tempo)[0])
        beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=hop)
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

    vf += ",format=yuv420p"

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
        image_path,
        "-ss",
        f"{start:.3f}",
        "-i",
        audio_path,
    ]
    if mode == "blur":
        cmd += ["-filter_complex", vf + "[v]", "-map", "[v]", "-map", "1:a:0"]
    else:
        cmd += ["-vf", vf, "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-af", af, "-t", f"{duration:.3f}", "-r", str(fps)]
    if use_nvenc and nvenc_available():
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-level", "4.1"]
    cmd += ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", "-shortest", output_path]
    _run(cmd)
    return output_path


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
