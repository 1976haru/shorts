from __future__ import annotations

import json
import math
import os
import random
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import pygame
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk
from tkinter import filedialog, messagebox, ttk
from tkinterdnd2 import DND_FILES, TkinterDnD

from shorts_core import *

APP_VERSION = "0.7.0"
SETTINGS_FILE = Path(__file__).with_name("settings.json")

BG = "#f4f6fb"
SURFACE = "#ffffff"
SURFACE_2 = "#eef2f7"
SURFACE_3 = "#e3e9f3"
BORDER = "#c8d2e1"
TEXT = "#1f2937"
MUTED = "#5f6b7a"
SUBTLE = "#7c8798"
ACCENT = "#2563eb"
ACCENT_2 = "#7c3aed"
SUCCESS = "#059669"
WARNING = "#d97706"
DANGER = "#e11d48"

MOTION_OPTIONS = [
    ("끔", "off"),
    ("감성형 랜덤", "sentimental_random"),
    ("천천히 줌인", "slow_zoom_in"),
    ("천천히 줌아웃", "slow_zoom_out"),
    ("왼쪽→오른쪽 팬", "pan_left_to_right"),
    ("오른쪽→왼쪽 팬", "pan_right_to_left"),
    ("위→아래", "pan_top_to_bottom"),
    ("아래→위", "pan_bottom_to_top"),
    ("대각선 이동", "diagonal_move"),
    ("중앙 확대 + 약한 회전", "center_zoom_rotate"),
    ("후렴 강조형", "chorus_zoom"),
    ("랜덤 프리셋", "random"),
]
MOTION_LABEL_TO_CODE = dict(MOTION_OPTIONS)
MOTION_CODE_TO_LABEL = {code: label for label, code in MOTION_OPTIONS}
LEGACY_MOTION_LABELS = {
    "zoom_in": "천천히 줌인",
    "zoom_out": "천천히 줌아웃",
    "pan_left": "오른쪽→왼쪽 팬",
    "pan_right": "왼쪽→오른쪽 팬",
    "gentle": "중앙 확대 + 약한 회전",
}

SENTIMENTAL_RANDOM_CODES = [
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left_to_right",
    "pan_right_to_left",
    "pan_top_to_bottom",
    "pan_bottom_to_top",
    "diagonal_move",
    "center_zoom_rotate",
]
FULL_RANDOM_CODES = SENTIMENTAL_RANDOM_CODES + ["chorus_zoom"]

INTENSITY_OPTIONS = [("약", "weak"), ("중", "medium"), ("강", "strong")]
INTENSITY_LABEL_TO_CODE = dict(INTENSITY_OPTIONS)
INTENSITY_CODE_TO_LABEL = {code: label for label, code in INTENSITY_OPTIONS}

BEAT_OPTIONS = [("끔", "off"), ("약", "weak"), ("중", "medium")]
BEAT_LABEL_TO_CODE = dict(BEAT_OPTIONS)
BEAT_CODE_TO_LABEL = {code: label for label, code in BEAT_OPTIONS}

OVERLAY_OPTIONS = [
    ("없음", "none"),
    ("필름그레인", "film_grain"),
    ("먼지", "dust"),
    ("빛샘", "light_leak"),
    ("비", "rain"),
    ("눈", "snow"),
    ("보케", "bokeh"),
]
OVERLAY_LABEL_TO_CODE = dict(OVERLAY_OPTIONS)
OVERLAY_CODE_TO_LABEL = {code: label for label, code in OVERLAY_OPTIONS}

SUBTITLE_POSITION_OPTIONS = [
    ("상단", "top"),
    ("중앙", "center"),
    ("하단", "bottom"),
    ("하단 안전영역", "safe_bottom"),
]
SUBTITLE_POSITION_LABEL_TO_CODE = dict(SUBTITLE_POSITION_OPTIONS)
SUBTITLE_POSITION_CODE_TO_LABEL = {code: label for label, code in SUBTITLE_POSITION_OPTIONS}

SUBTITLE_SIZE_OPTIONS = [("작게", "small"), ("보통", "medium"), ("크게", "large")]
SUBTITLE_SIZE_LABEL_TO_CODE = dict(SUBTITLE_SIZE_OPTIONS)
SUBTITLE_SIZE_CODE_TO_LABEL = {code: label for label, code in SUBTITLE_SIZE_OPTIONS}

SUBTITLE_STYLE_OPTIONS = [("감성형", "emotional"), ("틱톡형", "tiktok"), ("뮤직형", "music")]
SUBTITLE_STYLE_LABEL_TO_CODE = dict(SUBTITLE_STYLE_OPTIONS)
SUBTITLE_STYLE_CODE_TO_LABEL = {code: label for label, code in SUBTITLE_STYLE_OPTIONS}

META_TEMPLATES = ["감성형", "시니어 발라드", "일본 ChillRap"]


def fmt(sec):
    sec = max(0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:05.2f}"


def _choice_label(value, label_to_code, code_to_label, default_label, aliases=None):
    aliases = aliases or {}
    if value in label_to_code:
        return value
    if value in code_to_label:
        return code_to_label[value]
    if value in aliases:
        return aliases[value]
    return default_label


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"ShortsMaker Studio v{APP_VERSION}")
        self.geometry("1240x940")
        self.minsize(1080, 820)
        self.configure(bg=BG)
        self.option_add("*Font", "{Malgun Gothic} 10")
        self._setup_style()

        self.duration = tk.IntVar(value=45)
        self.mode = tk.StringVar(value="fill")
        self.zoom = tk.DoubleVar(value=6.0)
        self.fade = tk.DoubleVar(value=0.5)
        self.motion = tk.StringVar(value="감성형 랜덤")
        self.motion_intensity = tk.StringVar(value="중")
        self.transition_interval = tk.IntVar(value=5)
        self.beat_reactivity = tk.StringVar(value="끔")
        self.overlay_effect = tk.StringVar(value="없음")
        self.subtitle_position = tk.StringVar(value="하단 안전영역")
        self.subtitle_size = tk.StringVar(value="작게")
        self.subtitle_style = tk.StringVar(value="뮤직형")
        self.export_thumbnail = tk.BooleanVar(value=False)
        self.zip_after_dual = tk.BooleanVar(value=False)
        self.count_per_song = tk.IntVar(value=1)
        self.use_nvenc = tk.BooleanVar(value=False)
        self.skip_existing = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="준비 완료")

        self.audio = tk.StringVar()
        self.image = tk.StringVar()
        self.subtitle = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Videos" / "ShortsMaker"))
        self.batch_input = tk.StringVar()
        self.batch_output = tk.StringVar(value=str(Path.home() / "Videos" / "ShortsMaker_Batch"))
        self.dual_audio_a = tk.StringVar()
        self.dual_image_a = tk.StringVar()
        self.dual_subtitle_a = tk.StringVar()
        self.dual_output_a = tk.StringVar(value=str(Path.home() / "Videos" / "ShortsMaker_Dual"))
        self.dual_name_a = tk.StringVar()
        self.dual_audio_b = tk.StringVar()
        self.dual_image_b = tk.StringVar()
        self.dual_subtitle_b = tk.StringVar()
        self.dual_output_b = tk.StringVar(value=str(Path.home() / "Videos" / "ShortsMaker_Dual"))
        self.dual_name_b = tk.StringVar()
        self.dual_status_a = tk.StringVar(value="A세트 대기")
        self.dual_status_b = tk.StringVar(value="B세트 대기")
        self.dual_candidate_var_a = tk.IntVar(value=0)
        self.dual_candidate_var_b = tk.IntVar(value=0)
        self.dual_candidate_texts_a = [tk.StringVar(value=f"A 후보 {i + 1}: 분석 대기") for i in range(3)]
        self.dual_candidate_texts_b = [tk.StringVar(value=f"B 후보 {i + 1}: 분석 대기") for i in range(3)]
        self.last_dual_outputs_text = tk.StringVar(value="아직 듀얼 제작 결과가 없습니다.")
        self.social_input_video = tk.StringVar()
        self.social_batch_folder = tk.StringVar()
        self.social_status = tk.StringVar(value="SNS 호환 변환 대기")
        self.preview_slot = tk.StringVar(value="single")
        self.channel_name = tk.StringVar(value="My Music Channel")
        self.meta_template = tk.StringVar(value="감성형")
        self.auto_meta = tk.BooleanVar(value=True)
        self.auto_image = tk.BooleanVar(value=True)

        self.candidates = []
        self.dual_candidates = {"A": [], "B": []}
        self.batch_pairs = []
        self.cancel_requested = False
        self.preview_file = None
        self.wave_total = 0.0
        self.preview_canvas = None
        self.preview_photo = None
        self.dual_preview_canvas = None
        self.dual_preview_photo = None
        self.preview_after_id = None
        self.preview_started_at = time.perf_counter()
        self._preview_source_path = None
        self._preview_source_image = None
        self._preview_motion_code = "slow_zoom_in"

        self.load_settings()
        self._build()
        self._install_preview_traces()
        self._schedule_preview_refresh()
        self._animate_visual_preview()
        try:
            pygame.mixer.init()
        except Exception:
            pass

    def _setup_style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass

        s.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE_2, bordercolor=BORDER)
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=SURFACE)
        s.configure("TLabel", background=BG, foreground=TEXT)
        s.configure("Muted.TLabel", background=BG, foreground=MUTED)
        s.configure("Panel.TLabel", background=SURFACE, foreground=TEXT)
        s.configure("Status.TLabel", background=BG, foreground=ACCENT, font=("Malgun Gothic", 10, "bold"))
        s.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Malgun Gothic", 24, "bold"))
        s.configure("Version.TLabel", background=BG, foreground=ACCENT, font=("Malgun Gothic", 11, "bold"))

        s.configure(
            "TLabelframe",
            background=BG,
            foreground=TEXT,
            bordercolor=BORDER,
            relief="solid",
        )
        s.configure(
            "TLabelframe.Label",
            background=BG,
            foreground=TEXT,
            font=("Malgun Gothic", 10, "bold"),
        )

        s.configure("TButton", padding=(12, 8), background=SURFACE_3, foreground=TEXT, bordercolor=BORDER)
        s.map(
            "TButton",
            background=[("disabled", "#eef1f6"), ("pressed", "#d4deed"), ("active", "#dbe5f4")],
            foreground=[("disabled", "#9aa5b5"), ("active", TEXT)],
            bordercolor=[("focus", ACCENT), ("active", ACCENT)],
        )
        s.configure("Primary.TButton", background=ACCENT_2, foreground="#ffffff", bordercolor=ACCENT_2)
        s.map(
            "Primary.TButton",
            background=[("disabled", "#dcd8f4"), ("pressed", "#5b21b6"), ("active", "#6d28d9")],
            foreground=[("disabled", "#8b86a8"), ("active", "#ffffff")],
        )
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT)
        s.map("Accent.TButton", background=[("pressed", "#1d4ed8"), ("active", "#2563eb")])
        s.configure("Danger.TButton", background=DANGER, foreground="#ffffff", bordercolor=DANGER)
        s.map("Danger.TButton", background=[("pressed", "#be123c"), ("active", "#f43f5e")])

        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure(
            "TNotebook.Tab",
            padding=(20, 10),
            background=SURFACE_2,
            foreground=MUTED,
            bordercolor=BORDER,
            font=("Malgun Gothic", 10, "bold"),
        )
        s.map(
            "TNotebook.Tab",
            background=[("selected", ACCENT_2), ("active", SURFACE_3)],
            foreground=[("selected", "#ffffff"), ("active", TEXT)],
        )

        s.configure(
            "TEntry",
            padding=(8, 7),
            fieldbackground="#ffffff",
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=TEXT,
        )
        s.map(
            "TEntry",
            fieldbackground=[("disabled", "#edf1f6"), ("focus", "#fbfdff")],
            bordercolor=[("focus", ACCENT), ("active", ACCENT)],
            foreground=[("disabled", "#9aa5b5")],
        )

        s.configure(
            "TCombobox",
            padding=(8, 7),
            fieldbackground="#ffffff",
            background=SURFACE_3,
            foreground=TEXT,
            bordercolor=BORDER,
            arrowcolor=ACCENT,
        )
        s.map(
            "TCombobox",
            fieldbackground=[("readonly", "#ffffff"), ("focus", "#fbfdff")],
            foreground=[("readonly", TEXT)],
            bordercolor=[("focus", ACCENT), ("active", ACCENT)],
        )

        s.configure(
            "TCheckbutton",
            background=BG,
            foreground=TEXT,
            focuscolor=ACCENT,
            indicatorcolor="#ffffff",
        )
        s.map(
            "TCheckbutton",
            foreground=[("disabled", "#9aa5b5"), ("active", TEXT)],
            background=[("active", BG)],
            indicatorcolor=[("selected", ACCENT), ("active", SURFACE_3)],
        )
        s.configure("TRadiobutton", background=BG, foreground=TEXT, indicatorcolor="#ffffff")
        s.map(
            "TRadiobutton",
            foreground=[("disabled", "#9aa5b5"), ("active", TEXT)],
            indicatorcolor=[("selected", ACCENT), ("active", SURFACE_3)],
        )

        s.configure("Horizontal.TScale", background=BG, troughcolor="#dbe4f0", bordercolor=BORDER, sliderthickness=18)
        s.map("Horizontal.TScale", background=[("active", ACCENT)], troughcolor=[("active", "#d8e7ff")])

        s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor="#dbe4f0", bordercolor=BORDER)
        s.configure(
            "Treeview",
            background="#ffffff",
            fieldbackground="#ffffff",
            foreground=TEXT,
            rowheight=28,
            bordercolor=BORDER,
        )
        s.configure("Treeview.Heading", background=SURFACE_3, foreground=TEXT, font=("Malgun Gothic", 10, "bold"))
        s.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", TEXT)])
        s.configure("Vertical.TScrollbar", background=SURFACE_3, troughcolor=BG, arrowcolor=TEXT, bordercolor=BORDER)

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=18, pady=(16, 5))
        ttk.Label(top, text="ShortsMaker Studio", style="Title.TLabel").pack(side="left")
        ttk.Label(top, text=f"v{APP_VERSION}", style="Version.TLabel").pack(side="left", padx=8, pady=(9, 0))
        ttk.Label(
            self,
            text="제작 → 자막 → 메타데이터 → ZIP 패키지까지 한 번에",
            style="Muted.TLabel",
            font=("Malgun Gothic", 10),
        ).pack(anchor="w", padx=20)

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=14, pady=10)
        self.single = ttk.Frame(tabs)
        self.dual = ttk.Frame(tabs)
        self.batch = ttk.Frame(tabs)
        self.publish = ttk.Frame(tabs)
        tabs.add(self.single, text="단일 제작")
        tabs.add(self.dual, text="2개 동시 제작")
        tabs.add(self.batch, text="일괄 제작")
        tabs.add(self.publish, text="업로드 준비")

        self._common(self.single)
        self._single_ui()
        self._common(self.dual)
        self._dual_ui()
        self._common(self.batch)
        self._batch_ui()
        self._publish_ui()

        foot = ttk.Frame(self)
        foot.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Label(foot, text=f"NVENC: {'사용 가능' if nvenc_available() else '미감지'}", style="Muted.TLabel").pack(side="left")
        ttk.Button(foot, text="설정 저장", command=self.save_settings).pack(side="left", padx=10)
        ttk.Label(foot, textvariable=self.status, style="Status.TLabel").pack(side="right")

    def _common(self, parent):
        f = ttk.LabelFrame(parent, text="공통 설정")
        f.pack(fill="x", padx=10, pady=8)

        video = ttk.LabelFrame(f, text="영상")
        video.pack(fill="x", padx=10, pady=(8, 4))
        r = ttk.Frame(video)
        r.pack(fill="x", padx=8, pady=6)
        ttk.Label(r, text="길이", width=8).pack(side="left")
        for v in (30, 45, 60):
            ttk.Radiobutton(r, text=f"{v}초", variable=self.duration, value=v).pack(side="left", padx=3)
        ttk.Label(r, text="곡당", width=7).pack(side="left", padx=(18, 0))
        ttk.Radiobutton(r, text="1개", variable=self.count_per_song, value=1).pack(side="left")
        ttk.Radiobutton(r, text="3개", variable=self.count_per_song, value=3).pack(side="left", padx=5)
        ttk.Label(r, text="화면", width=7).pack(side="left", padx=(18, 0))
        ttk.Radiobutton(r, text="Fill", variable=self.mode, value="fill").pack(side="left")
        ttk.Radiobutton(r, text="Blur", variable=self.mode, value="blur").pack(side="left", padx=5)
        ttk.Checkbutton(r, text="이미지 9:16 자동 전처리", variable=self.auto_image).pack(side="left", padx=(18, 6))
        ttk.Checkbutton(r, text="NVENC", variable=self.use_nvenc).pack(side="left", padx=6)
        ttk.Checkbutton(r, text="기존 파일 건너뛰기", variable=self.skip_existing).pack(side="left", padx=6)

        motion = ttk.LabelFrame(f, text="모션")
        motion.pack(fill="x", padx=10, pady=4)
        r2 = ttk.Frame(motion)
        r2.pack(fill="x", padx=8, pady=6)
        self._combo(r2, "애니메이션", self.motion, [label for label, _ in MOTION_OPTIONS], 18)
        self._combo(r2, "강도", self.motion_intensity, [label for label, _ in INTENSITY_OPTIONS], 7)
        self._combo(r2, "전환 간격", self.transition_interval, [3, 5, 8, 10], 6)
        self._combo(r2, "비트 반응", self.beat_reactivity, [label for label, _ in BEAT_OPTIONS], 7)
        self._combo(r2, "오버레이", self.overlay_effect, [label for label, _ in OVERLAY_OPTIONS], 10)

        r4 = ttk.Frame(motion)
        r4.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(r4, text="Zoom", width=8).pack(side="left")
        ttk.Scale(r4, from_=0, to=12, variable=self.zoom).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(r4, textvariable=self.zoom, width=5, foreground=ACCENT).pack(side="left")
        ttk.Label(r4, text="Fade", width=7).pack(side="left", padx=(16, 0))
        ttk.Scale(r4, from_=0, to=2, variable=self.fade).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Label(r4, textvariable=self.fade, width=5, foreground=ACCENT).pack(side="left")

        caption = ttk.LabelFrame(f, text="자막")
        caption.pack(fill="x", padx=10, pady=(4, 8))
        r3 = ttk.Frame(caption)
        r3.pack(fill="x", padx=8, pady=6)
        self._combo(r3, "자막 위치", self.subtitle_position, [label for label, _ in SUBTITLE_POSITION_OPTIONS], 12)
        self._combo(r3, "자막 크기", self.subtitle_size, [label for label, _ in SUBTITLE_SIZE_OPTIONS], 8)
        self._combo(r3, "자막 스타일", self.subtitle_style, [label for label, _ in SUBTITLE_STYLE_OPTIONS], 9)
        ttk.Label(r3, text="기본 안전영역: 하단 220~300px").pack(side="left", padx=(4, 0))

    def _combo(self, parent, label, variable, values, width):
        ttk.Label(parent, text=label).pack(side="left", padx=(0, 4))
        cb = ttk.Combobox(parent, textvariable=variable, state="readonly", values=values, width=width)
        cb.pack(side="left", padx=(0, 12))
        return cb

    def _pathrow(self, parent, label, var, cmd, drop=False):
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text=label, width=12).pack(side="left")
        e = ttk.Entry(r, textvariable=var)
        e.pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(r, text="찾기", command=cmd, width=9).pack(side="left")
        if drop:
            e.drop_target_register(DND_FILES)
            e.dnd_bind("<<Drop>>", lambda ev, v=var: self._drop(ev, v))
        return e

    def _drop(self, event, var):
        paths = self.tk.splitlist(event.data)
        if paths:
            var.set(paths[0])

    def _single_ui(self):
        b = ttk.Frame(self.single)
        b.pack(fill="both", expand=True, padx=10, pady=4)

        left = ttk.Frame(b)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ttk.Frame(b)
        right.pack(side="right", fill="y")

        self._pathrow(left, "음원", self.audio, self.pick_audio, True)
        self._pathrow(left, "이미지", self.image, self.pick_image, True)
        self._pathrow(left, "자막 SRT", self.subtitle, self.pick_subtitle, True)
        self._pathrow(left, "출력 폴더", self.output_dir, self.pick_output)

        r = ttk.Frame(left)
        r.pack(fill="x", pady=6)
        ttk.Button(r, text="TOP3 분석", command=self.analyze, style="Accent.TButton").pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(r, text="미리듣기", command=self.preview).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(r, text="정지", command=self.stop_preview).pack(side="left", padx=4)
        ttk.Button(r, text="선택 후보 제작", command=self.render_selected, style="Primary.TButton").pack(side="left", fill="x", expand=True, padx=(4, 0))

        wf = ttk.LabelFrame(left, text="파형 / TOP3 위치")
        wf.pack(fill="x", pady=6)
        self.canvas = tk.Canvas(wf, height=150, bg="#ffffff", highlightthickness=1, highlightbackground=BORDER)
        self.canvas.pack(fill="x", expand=True, padx=8, pady=8)

        c = ttk.LabelFrame(left, text="하이라이트 TOP3")
        c.pack(fill="x", pady=5)
        self.candidate_var = tk.IntVar(value=0)
        self.candidate_texts = [tk.StringVar(value=f"후보 {i + 1}: 분석 대기") for i in range(3)]
        for i in range(3):
            rr = ttk.Frame(c)
            rr.pack(fill="x", padx=6, pady=3)
            ttk.Radiobutton(rr, variable=self.candidate_var, value=i).pack(side="left")
            ttk.Label(rr, textvariable=self.candidate_texts[i]).pack(side="left")
        self.p1 = ttk.Progressbar(left, mode="indeterminate")
        self.p1.pack(fill="x", pady=8)

        pv = ttk.LabelFrame(right, text="숏츠 미리보기")
        pv.pack(fill="y", expand=False)
        self.preview_canvas = tk.Canvas(pv, width=280, height=498, bg="#edf3fb", highlightthickness=1, highlightbackground=BORDER)
        self.preview_canvas.pack(padx=10, pady=10)
        ttk.Label(pv, textvariable=self._preview_summary_var(), style="Muted.TLabel", wraplength=280, justify="center").pack(
            fill="x", padx=10, pady=(0, 10)
        )

    def _dual_ui(self):
        b = ttk.Frame(self.dual)
        b.pack(fill="both", expand=True, padx=10, pady=4)

        body = ttk.Frame(b)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right = ttk.Frame(body)
        right.pack(side="right", fill="y")

        slots = ttk.Frame(left)
        slots.pack(fill="x")
        self._dual_slot_ui(
            slots,
            "A세트",
            self.dual_audio_a,
            self.dual_image_a,
            self.dual_subtitle_a,
            self.dual_output_a,
            self.dual_name_a,
            self.dual_status_a,
            "A",
        )
        self._dual_slot_ui(
            slots,
            "B세트",
            self.dual_audio_b,
            self.dual_image_b,
            self.dual_subtitle_b,
            self.dual_output_b,
            self.dual_name_b,
            self.dual_status_b,
            "B",
        )

        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=8)
        ttk.Button(actions, text="숏츠 2개 제작", command=self.start_dual_render, style="Primary.TButton").pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        ttk.Button(actions, text="A 미리보기", command=lambda: self.set_preview_slot("A")).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(actions, text="B 미리보기", command=lambda: self.set_preview_slot("B")).pack(side="left", fill="x", expand=True, padx=(4, 0))

        opts = ttk.Frame(left)
        opts.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(opts, text="썸네일 자동 저장", variable=self.export_thumbnail).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(opts, text="완료 후 ZIP 패키지", variable=self.zip_after_dual).pack(side="left")

        status_box = ttk.LabelFrame(left, text="A/B 진행 상태")
        status_box.pack(fill="x", pady=6)
        ttk.Label(status_box, textvariable=self.dual_status_a).pack(anchor="w", padx=10, pady=(8, 2))
        ttk.Label(status_box, textvariable=self.dual_status_b).pack(anchor="w", padx=10, pady=(2, 8))
        self.p_dual = ttk.Progressbar(status_box, mode="determinate", maximum=2)
        self.p_dual.pack(fill="x", padx=10, pady=(0, 10))

        log_box = ttk.LabelFrame(left, text="듀얼 제작 로그")
        log_box.pack(fill="both", expand=True, pady=6)
        self.dual_log = tk.Text(
            log_box,
            height=7,
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#dbeafe",
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
        )
        self.dual_log.pack(fill="both", expand=True, padx=6, pady=6)

        pv = ttk.LabelFrame(right, text="A/B 미리보기")
        pv.pack(fill="y", expand=False)
        self.dual_preview_canvas = tk.Canvas(pv, width=280, height=498, bg="#edf3fb", highlightthickness=1, highlightbackground=BORDER)
        self.dual_preview_canvas.pack(padx=10, pady=10)
        ttk.Label(pv, textvariable=self.preview_summary, style="Muted.TLabel", wraplength=280, justify="center").pack(
            fill="x", padx=10, pady=(0, 10)
        )

    def _dual_slot_ui(self, parent, title, audio, image, subtitle, output, name, status, slot):
        box = ttk.LabelFrame(parent, text=title)
        box.pack(side="left", fill="both", expand=True, padx=(0, 6) if slot == "A" else (6, 0), pady=6)
        self._pathrow(box, "음원", audio, lambda v=audio: self.pick_audio_var(v), True)
        self._pathrow(box, "이미지", image, lambda v=image: self.pick_image_var(v), True)
        self._pathrow(box, "자막 SRT", subtitle, lambda v=subtitle: self.pick_subtitle_var(v), True)
        self._pathrow(box, "출력 폴더", output, lambda v=output: self.pick_directory_var(v))

        row = ttk.Frame(box)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text="출력 파일명", width=12).pack(side="left")
        ttk.Entry(row, textvariable=name).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(row, text=f"{slot} 미리보기", command=lambda s=slot: self.set_preview_slot(s), width=11).pack(side="left")
        ttk.Label(box, textvariable=status, style="Muted.TLabel").pack(anchor="w", padx=8, pady=(2, 6))
        ttk.Button(box, text=f"{slot} TOP3 분석", command=lambda s=slot: self.analyze_dual_slot(s)).pack(fill="x", padx=8, pady=(0, 4))
        cand_var = self.dual_candidate_var_a if slot == "A" else self.dual_candidate_var_b
        cand_texts = self.dual_candidate_texts_a if slot == "A" else self.dual_candidate_texts_b
        for i in range(3):
            rr = ttk.Frame(box)
            rr.pack(fill="x", padx=8, pady=1)
            ttk.Radiobutton(rr, variable=cand_var, value=i).pack(side="left")
            ttk.Label(rr, textvariable=cand_texts[i], style="Muted.TLabel").pack(side="left")

    def _batch_ui(self):
        b = ttk.Frame(self.batch)
        b.pack(fill="both", expand=True, padx=10, pady=4)
        self._pathrow(b, "입력 폴더", self.batch_input, self.pick_batch_input, True)
        self._pathrow(b, "출력 폴더", self.batch_output, self.pick_batch_output)
        r = ttk.Frame(b)
        r.pack(fill="x", pady=6)
        ttk.Button(r, text="파일 스캔", command=self.scan_batch).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(r, text="일괄 제작 시작", command=self.start_batch, style="Primary.TButton").pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(r, text="작업 중지", command=self.cancel_batch, style="Danger.TButton").pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(r, text="로그 저장", command=self.save_log).pack(side="left", fill="x", expand=True, padx=(4, 0))

        box = ttk.LabelFrame(b, text="매칭 목록")
        box.pack(fill="both", expand=True, pady=5)
        self.tree = ttk.Treeview(box, columns=("a", "i", "m"), show="headings", height=10)
        for col, txt, w in [("a", "음원", 380), ("i", "이미지", 380), ("m", "매칭", 120)]:
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.p2 = ttk.Progressbar(b, mode="determinate")
        self.p2.pack(fill="x", pady=5)
        lf = ttk.LabelFrame(b, text="로그")
        lf.pack(fill="both", expand=True, pady=5)
        self.log = tk.Text(
            lf,
            height=9,
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#dbeafe",
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
        )
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

    def _publish_ui(self):
        b = ttk.Frame(self.publish)
        b.pack(fill="both", expand=True, padx=14, pady=14)
        f = ttk.LabelFrame(b, text="채널/메타데이터 설정")
        f.pack(fill="x", pady=6)
        r = ttk.Frame(f)
        r.pack(fill="x", padx=8, pady=8)
        ttk.Label(r, text="채널명", width=12).pack(side="left")
        ttk.Entry(r, textvariable=self.channel_name).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Label(r, text="프리셋", width=8).pack(side="left", padx=(12, 0))
        ttk.Combobox(r, textvariable=self.meta_template, state="readonly", values=META_TEMPLATES, width=18).pack(side="left")
        ttk.Checkbutton(r, text="영상 제작 후 업로드정보 자동 생성", variable=self.auto_meta).pack(side="left", padx=12)

        z = ttk.LabelFrame(b, text="패키지")
        z.pack(fill="x", pady=8)
        rr = ttk.Frame(z)
        rr.pack(fill="x", padx=8, pady=8)
        ttk.Button(rr, text="단일 출력 폴더 ZIP 만들기", command=lambda: self.make_zip(self.output_dir.get())).pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        ttk.Button(rr, text="일괄 출력 폴더 ZIP 만들기", command=lambda: self.make_zip(self.batch_output.get())).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        social = ttk.LabelFrame(b, text="SNS 호환 변환")
        social.pack(fill="x", pady=8)
        self._pathrow(social, "기존 MP4", self.social_input_video, self.pick_social_video, True)
        sr = ttk.Frame(social)
        sr.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Button(sr, text="SNS 호환 변환", command=self.start_social_convert, style="Accent.TButton").pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        ttk.Label(sr, textvariable=self.social_status, style="Muted.TLabel").pack(side="left", padx=8)
        self._pathrow(social, "MP4 폴더", self.social_batch_folder, self.pick_social_folder, True)
        br = ttk.Frame(social)
        br.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Button(br, text="Batch SNS 호환 변환", command=self.start_batch_social_convert).pack(
            side="left", fill="x", expand=True
        )
        self.social_log = tk.Text(
            social,
            height=5,
            bg="#ffffff",
            fg=TEXT,
            insertbackground=TEXT,
            selectbackground="#dbeafe",
            relief="flat",
            wrap="word",
            padx=10,
            pady=8,
        )
        self.social_log.pack(fill="x", padx=8, pady=(0, 8))

        dual = ttk.LabelFrame(b, text="오늘 만든 숏츠 2개")
        dual.pack(fill="x", pady=8)
        ttk.Label(dual, textvariable=self.last_dual_outputs_text, justify="left", wraplength=900).pack(anchor="w", padx=10, pady=10)

        info = ttk.LabelFrame(b, text=f"v{APP_VERSION} 사용 흐름")
        info.pack(fill="both", expand=True, pady=8)
        text = (
            "1. 음원 + 이미지 선택\n"
            "2. TOP3 하이라이트 분석\n"
            "3. 필요하면 SRT 자막 추가\n"
            "4. 선택 후보 또는 일괄 제작\n"
            "5. 업로드정보 TXT 자동 생성\n"
            "6. 결과 폴더를 ZIP으로 묶어 보관/전달\n\n"
            "자막은 SRT 파일을 제공한 경우에만 영상에 삽입됩니다."
        )
        ttk.Label(info, text=text, justify="left", font=("Malgun Gothic", 11)).pack(anchor="nw", padx=12, pady=12)

    def _preview_summary_var(self):
        self.preview_summary = tk.StringVar()
        return self.preview_summary

    def _install_preview_traces(self):
        for var in (
            self.image,
            self.subtitle,
            self.dual_image_a,
            self.dual_subtitle_a,
            self.dual_image_b,
            self.dual_subtitle_b,
            self.preview_slot,
            self.motion,
            self.motion_intensity,
            self.transition_interval,
            self.beat_reactivity,
            self.overlay_effect,
            self.subtitle_position,
            self.subtitle_size,
            self.subtitle_style,
            self.zoom,
        ):
            var.trace_add("write", lambda *_: self._schedule_preview_refresh())

    def _schedule_preview_refresh(self):
        self._preview_motion_code = self._motion_code(for_preview=True)
        if hasattr(self, "preview_summary"):
            slot = self._preview_slot_label()
            self.preview_summary.set(
                f"{slot} · {self.motion.get()} · {self.motion_intensity.get()} · {self.transition_interval.get()}초 · "
                f"{self.subtitle_position.get()} / {self.subtitle_size.get()} / {self.subtitle_style.get()}"
            )
        self.preview_started_at = time.perf_counter()

    def set_preview_slot(self, slot):
        self.preview_slot.set(slot)
        self._schedule_preview_refresh()

    def _preview_slot_label(self):
        return {"single": "단일", "A": "A세트", "B": "B세트"}.get(self.preview_slot.get(), "단일")

    def _current_preview_image_path(self):
        if self.preview_slot.get() == "A":
            return self.dual_image_a.get()
        if self.preview_slot.get() == "B":
            return self.dual_image_b.get()
        return self.image.get()

    def _current_preview_subtitle_path(self):
        if self.preview_slot.get() == "A":
            return self.dual_subtitle_a.get()
        if self.preview_slot.get() == "B":
            return self.dual_subtitle_b.get()
        return self.subtitle.get()

    def _load_preview_image(self):
        path = self._current_preview_image_path()
        if path == self._preview_source_path:
            return self._preview_source_image
        self._preview_source_path = path
        self._preview_source_image = None
        if path and Path(path).exists():
            try:
                self._preview_source_image = Image.open(path).convert("RGB")
            except Exception:
                self._preview_source_image = None
        return self._preview_source_image

    def _animate_visual_preview(self):
        if self.preview_canvas is not None:
            self._draw_visual_preview(self.preview_canvas, "preview_photo")
        if self.dual_preview_canvas is not None:
            self._draw_visual_preview(self.dual_preview_canvas, "dual_preview_photo")
        self.preview_after_id = self.after(80, self._animate_visual_preview)

    def _draw_visual_preview(self, canvas=None, photo_attr="preview_photo"):
        c = canvas or self.preview_canvas
        c.delete("all")
        w = max(220, c.winfo_width() or 280)
        h = max(390, c.winfo_height() or 498)
        elapsed = time.perf_counter() - self.preview_started_at
        img = self._load_preview_image()

        if img is None:
            self._draw_preview_placeholder(c, w, h, elapsed)
        else:
            frame = self._preview_frame(img, w, h, elapsed)
            photo = ImageTk.PhotoImage(frame)
            setattr(self, photo_attr, photo)
            c.create_image(0, 0, anchor="nw", image=photo)

        self._draw_overlay_badges(c, w)
        self._draw_safe_zone_guides(c, w, h)
        self._draw_caption_preview(c, w, h)

    def _draw_preview_placeholder(self, c, w, h, elapsed):
        for i in range(18):
            t = i / 17
            r = int(238 + 10 * t)
            g = int(243 + 8 * t)
            b = int(250 + 3 * t)
            c.create_rectangle(0, h * t, w, h * (t + 1 / 17), fill=f"#{r:02x}{g:02x}{b:02x}", outline="")
        drift = 0 if self._preview_motion_code == "off" else 1
        cx = w / 2 + math.sin(elapsed * 0.7) * 12 * drift
        cy = h / 2 + math.cos(elapsed * 0.5) * 18 * drift
        c.create_oval(cx - 70, cy - 70, cx + 70, cy + 70, outline="#cad6e8", width=2)
        c.create_text(w / 2, h / 2, text="이미지 선택 대기", fill=MUTED, font=("Malgun Gothic", 13, "bold"))

    def _preview_frame(self, img, w, h, elapsed):
        code = self._preview_motion_code
        if code == "off":
            cover = max(w / img.width, h / img.height)
            rw = max(w, int(img.width * cover))
            rh = max(h, int(img.height * cover))
            resized = img.resize((rw, rh), Image.LANCZOS)
            left = max(0, (rw - w) // 2)
            top = max(0, (rh - h) // 2)
            return resized.crop((left, top, left + w, top + h))
        period = max(3, int(self.transition_interval.get() or 5))
        p = (elapsed % period) / period
        eased = 0.5 - 0.5 * math.cos(2 * math.pi * p)
        strength = {"약": 0.7, "중": 1.0, "강": 1.35}.get(self.motion_intensity.get(), 1.0)
        base_zoom = 1.0 + max(0.0, float(self.zoom.get() or 6.0)) / 100.0 * strength
        pan_zoom = max(base_zoom, 1.08 + 0.03 * strength)
        beat = 0.0
        if self.beat_reactivity.get() == "약":
            beat = 0.008 * max(0.0, math.sin(2 * math.pi * p * 2))
        elif self.beat_reactivity.get() == "중":
            beat = 0.014 * max(0.0, math.sin(2 * math.pi * p * 2))

        zoom = base_zoom + beat
        nx = ny = 0.5
        angle = 0.0

        if code == "emotional_random":
            zoom = 1.0 + (base_zoom - 1.0) * (0.35 + 0.65 * eased) + beat
            nx = 0.5 + 0.24 * math.sin(2 * math.pi * p)
            ny = 0.5 + 0.16 * math.cos(2 * math.pi * p)
        elif code == "slow_zoom_out":
            zoom = base_zoom - (base_zoom - 1.0) * eased + beat
        elif code == "pan_left_to_right":
            zoom, nx = pan_zoom + beat, eased
        elif code == "pan_right_to_left":
            zoom, nx = pan_zoom + beat, 1.0 - eased
        elif code == "pan_top_to_bottom":
            zoom, ny = pan_zoom + beat, eased
        elif code == "pan_bottom_to_top":
            zoom, ny = pan_zoom + beat, 1.0 - eased
        elif code == "diagonal_move":
            zoom, nx, ny = pan_zoom + beat, eased, 0.18 + 0.64 * eased
        elif code == "center_zoom_rotate":
            angle = math.sin(2 * math.pi * p) * 0.8
        elif code == "chorus_zoom":
            zoom = base_zoom + 0.025 * strength * max(0.0, math.sin(math.pi * min(1.0, max(0.0, (p - 0.32) / 0.24)))) + beat

        cover = max(w / img.width, h / img.height) * zoom
        rw = max(w, int(img.width * cover))
        rh = max(h, int(img.height * cover))
        resized = img.resize((rw, rh), Image.LANCZOS)
        if angle:
            resized = resized.rotate(angle, resample=Image.BICUBIC, expand=False)
        max_x = max(0, rw - w)
        max_y = max(0, rh - h)
        left = int(max_x * nx)
        top = int(max_y * ny)
        frame = resized.crop((left, top, left + w, top + h))

        overlay = self.overlay_effect.get()
        if overlay != "없음":
            frame = self._apply_preview_overlay(frame, overlay, elapsed)
        return frame

    def _apply_preview_overlay(self, frame, overlay, elapsed):
        overlay_img = frame.copy()
        draw = ImageDraw.Draw(overlay_img, "RGBA")
        w, h = frame.size
        if overlay == "필름그레인":
            random.seed(int(elapsed * 12))
            for _ in range(900):
                x = random.randrange(w)
                y = random.randrange(h)
                a = random.randrange(10, 26)
                draw.point((x, y), fill=(255, 255, 255, a))
        elif overlay == "먼지":
            random.seed(21)
            for _ in range(34):
                x = (random.randrange(w) + int(elapsed * 8)) % w
                y = random.randrange(h)
                r = random.randrange(1, 3)
                draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 240, 210, 32))
        elif overlay == "빛샘":
            draw.ellipse((-w * 0.3, -h * 0.18, w * 0.75, h * 0.42), fill=(255, 184, 105, 38))
        elif overlay == "비":
            random.seed(int(elapsed * 16))
            for _ in range(42):
                x = random.randrange(w)
                y = random.randrange(h)
                draw.line((x, y, x + 8, y + 22), fill=(180, 220, 255, 42), width=1)
        elif overlay == "눈":
            random.seed(int(elapsed * 10))
            for _ in range(55):
                x = random.randrange(w)
                y = random.randrange(h)
                r = random.randrange(1, 3)
                draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 50))
        elif overlay == "보케":
            random.seed(12)
            for _ in range(12):
                x = random.randrange(w)
                y = random.randrange(h)
                r = random.randrange(8, 26)
                draw.ellipse((x - r, y - r, x + r, y + r), outline=(255, 230, 180, 34), width=2)
        return overlay_img

    def _draw_overlay_badges(self, c, w):
        label = self.motion.get()
        subtitle = f"{self.subtitle_position.get()} · {self.subtitle_size.get()} · {self.subtitle_style.get()}"
        self._pill(c, 12, 12, f"{self._preview_slot_label()} · ANIM {label}", ACCENT_2)
        self._pill(c, 12, 42, f"CAPTION {subtitle}", "#1f7a9d")

    def _draw_safe_zone_guides(self, c, w, h):
        top = int(h * 0.08)
        bottom = int(h * 0.90)
        caption_top = int(h * 0.76)
        caption_bottom = int(h * 0.91)
        c.create_rectangle(10, top, w - 10, bottom, outline="#b6c5da", dash=(4, 4))
        c.create_rectangle(18, caption_top, w - 18, caption_bottom, outline="#2563eb", dash=(3, 3))

    def _pill(self, c, x, y, text, fill):
        font = ("Malgun Gothic", 9, "bold")
        tid = c.create_text(x + 10, y + 9, text=text, anchor="w", fill="#ffffff", font=font)
        bbox = c.bbox(tid)
        c.delete(tid)
        c.create_rectangle(x, y, bbox[2] - bbox[0] + x + 20, y + 22, fill=fill, outline="", stipple="")
        c.create_text(x + 10, y + 11, text=text, anchor="w", fill="#ffffff", font=font)

    def _draw_caption_preview(self, c, w, h):
        text = self._subtitle_preview_text()
        pos = self.subtitle_position.get()
        y = {"상단": h * 0.13, "중앙": h * 0.52, "하단": h * 0.91, "하단 안전영역": h * 0.86}.get(pos, h * 0.86)
        anchor = "n" if pos == "상단" else "center" if pos == "중앙" else "s"
        size = {"작게": 15, "보통": 18, "크게": 22}.get(self.subtitle_size.get(), 18)
        style = self.subtitle_style.get()
        if style == "틱톡형":
            font = ("Malgun Gothic", size, "bold")
            fill = "#ffffff"
            outline = "#000000"
            width = 2
        elif style == "뮤직형":
            font = ("Malgun Gothic", size)
            fill = "#f7efe2"
            outline = "#1a120b"
            width = 1
        else:
            font = ("Malgun Gothic", size)
            fill = "#ffffff"
            outline = "#050912"
            width = 1
        self._outlined_text(c, w / 2, y, text, font, fill, outline, width, min(240, int(w * 0.84)), anchor)

    def _outlined_text(self, c, x, y, text, font, fill, outline, width_px, text_width, anchor):
        offsets = []
        for dx in range(-width_px, width_px + 1):
            for dy in range(-width_px, width_px + 1):
                if dx or dy:
                    offsets.append((dx, dy))
        for dx, dy in offsets:
            c.create_text(x + dx, y + dy, text=text, fill=outline, font=font, width=text_width, justify="center", anchor=anchor)
        c.create_text(x, y, text=text, fill=fill, font=font, width=text_width, justify="center", anchor=anchor)

    def _subtitle_preview_text(self):
        path = self._current_preview_subtitle_path()
        if path and Path(path).exists():
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    raw = Path(path).read_text(encoding=enc)
                    break
                except Exception:
                    raw = ""
            lines = []
            for line in raw.splitlines():
                stripped = line.strip()
                if not stripped or stripped.isdigit() or "-->" in stripped:
                    if lines:
                        break
                    continue
                lines.append(stripped)
                if len(lines) >= 3:
                    break
            if lines:
                return "\n".join(lines[:3])
        return "I still remember the melody\n아직도 그 멜로디가 떠올라"

    def _motion_code(self, for_preview=False):
        label = self.motion.get()
        code = MOTION_LABEL_TO_CODE.get(label, label)
        if code == "sentimental_random":
            return "emotional_random"
        if code == "random":
            if for_preview:
                return random.choice(FULL_RANDOM_CODES)
            return random.choice(FULL_RANDOM_CODES)
        return code if code in FULL_RANDOM_CODES + ["off"] else "slow_zoom_in"

    def _render_options(self):
        return {
            "subtitle_position": SUBTITLE_POSITION_LABEL_TO_CODE.get(self.subtitle_position.get(), "safe_bottom"),
            "subtitle_size": SUBTITLE_SIZE_LABEL_TO_CODE.get(self.subtitle_size.get(), "medium"),
            "subtitle_style": SUBTITLE_STYLE_LABEL_TO_CODE.get(self.subtitle_style.get(), "emotional"),
            "motion_intensity": INTENSITY_LABEL_TO_CODE.get(self.motion_intensity.get(), "medium"),
            "transition_interval": int(self.transition_interval.get() or 5),
            "beat_reactivity": BEAT_LABEL_TO_CODE.get(self.beat_reactivity.get(), "off"),
            "overlay_effect": OVERLAY_LABEL_TO_CODE.get(self.overlay_effect.get(), "none"),
        }

    def pick_audio(self):
        p = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.aac *.ogg *.opus")])
        if p:
            self.preview_slot.set("single")
            self.audio.set(p)

    def pick_image(self):
        p = filedialog.askopenfilename(filetypes=[("Image", "*.jpg *.jpeg *.png *.webp *.bmp")])
        if p:
            self.preview_slot.set("single")
            self.image.set(p)

    def pick_subtitle(self):
        p = filedialog.askopenfilename(filetypes=[("Subtitle", "*.srt"), ("All", "*.*")])
        if p:
            self.preview_slot.set("single")
            self.subtitle.set(p)

    def pick_output(self):
        p = filedialog.askdirectory()
        if p:
            self.output_dir.set(p)

    def pick_audio_var(self, var):
        p = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.aac *.ogg *.opus")])
        if p:
            var.set(p)

    def pick_image_var(self, var):
        p = filedialog.askopenfilename(filetypes=[("Image", "*.jpg *.jpeg *.png *.webp *.bmp")])
        if p:
            var.set(p)

    def pick_subtitle_var(self, var):
        p = filedialog.askopenfilename(filetypes=[("Subtitle", "*.srt"), ("All", "*.*")])
        if p:
            var.set(p)

    def pick_directory_var(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(p)

    def pick_batch_input(self):
        p = filedialog.askdirectory()
        if p:
            self.batch_input.set(p)

    def pick_batch_output(self):
        p = filedialog.askdirectory()
        if p:
            self.batch_output.set(p)

    def pick_social_video(self):
        p = filedialog.askopenfilename(filetypes=[("MP4", "*.mp4"), ("All", "*.*")])
        if p:
            self.social_input_video.set(p)

    def pick_social_folder(self):
        p = filedialog.askdirectory()
        if p:
            self.social_batch_folder.set(p)

    def _compatibility_status(self, validation):
        return "PASS" if validation.get("compatible") else "FAIL"

    def _format_compatibility_result(self, validation):
        status = self._compatibility_status(validation)
        lines = [f"TikTok / YouTube Shorts 호환성: {status}"]
        lines.append(
            f"{validation.get('video_codec') or '-'} {validation.get('resolution') or '-'} "
            f"{validation.get('fps') or '-'}fps {validation.get('pixel_format') or '-'} "
            f"{validation.get('color_space') or '-'} / {validation.get('color_range') or '-'}"
        )
        lines.append(
            f"{validation.get('audio_codec') or '-'} {validation.get('sample_rate') or '-'}Hz "
            f"{validation.get('channels') or '-'}ch"
        )
        for issue in validation.get("issues") or []:
            lines.append(f"* {issue}")
        return "\n".join(lines)

    def _social_log(self, message):
        if hasattr(self, "social_log"):
            self.social_log.insert("end", message + "\n")
            self.social_log.see("end")

    def start_social_convert(self):
        src = self.social_input_video.get()
        if not src or not Path(src).exists():
            messagebox.showwarning("확인", "변환할 MP4 파일을 선택하세요.")
            return
        self.social_status.set("SNS 호환 변환 중")
        self.status.set("SNS 호환 변환 중")
        threading.Thread(target=self._social_convert_worker, args=(src,), daemon=True).start()

    def _social_convert_worker(self, src):
        try:
            result = convert_to_social_compatible(src, use_nvenc=self.use_nvenc.get())
            self.after(0, lambda r=result: self._social_convert_done(r))
        except Exception as e:
            self.after(
                0,
                lambda err=str(e): (
                    self.social_status.set("SNS 호환 변환 실패"),
                    self.status.set("SNS 변환 실패"),
                    self._social_log(f"FAIL: {err}"),
                    messagebox.showerror("SNS 호환 변환 실패", err),
                ),
            )

    def _social_convert_done(self, result):
        validation = result["validation"]
        status = self._compatibility_status(validation)
        output = result["output_path"]
        self.social_status.set(f"SNS 호환 변환 {status}")
        self.status.set(f"SNS 호환 변환 {status}")
        message = f"{output}\n\n{self._format_compatibility_result(validation)}"
        self._social_log(message)
        messagebox.showinfo("SNS 호환 변환 완료", message)

    def start_batch_social_convert(self):
        folder = self.social_batch_folder.get()
        if not folder or not Path(folder).exists():
            messagebox.showwarning("확인", "변환할 MP4 폴더를 선택하세요.")
            return
        self.social_status.set("Batch SNS 호환 변환 중")
        self.status.set("Batch SNS 호환 변환 중")
        threading.Thread(target=self._batch_social_convert_worker, args=(folder,), daemon=True).start()

    def _batch_social_convert_worker(self, folder):
        results = batch_convert_to_social_compatible(folder, use_nvenc=self.use_nvenc.get())
        self.after(0, lambda r=results: self._batch_social_convert_done(r))

    def _batch_social_convert_done(self, results):
        passed = sum(1 for r in results if r.get("validation", {}).get("compatible"))
        failed = len(results) - passed
        self.social_status.set(f"Batch 완료: PASS {passed}, FAIL {failed}")
        self.status.set("Batch SNS 호환 변환 완료")
        if not results:
            self._social_log("변환할 MP4가 없습니다.")
            return
        for result in results:
            validation = result.get("validation", {})
            output = result.get("output_path") or result.get("input_path")
            self._social_log(f"{self._compatibility_status(validation)}: {output}")
            for issue in validation.get("issues") or []:
                self._social_log(f"* {issue}")

    def analyze_dual_slot(self, slot):
        audio = self.dual_audio_a.get() if slot == "A" else self.dual_audio_b.get()
        status = self.dual_status_a if slot == "A" else self.dual_status_b
        if not Path(audio).exists():
            messagebox.showwarning("확인", f"{slot}세트 음원을 선택하세요.")
            return
        status.set(f"{slot}세트 TOP3 분석 중")
        self._dual_log(f"{slot}세트 TOP3 분석 중")
        threading.Thread(target=self._dual_analyze_worker, args=(slot, audio), daemon=True).start()

    def _dual_analyze_worker(self, slot, audio):
        try:
            res = analyze_top_highlights(audio, self.duration.get(), 3)
            self.after(0, lambda: self._dual_analysis_done(slot, res))
        except Exception as e:
            self.after(0, lambda err=str(e): self._dual_analysis_failed(slot, err))

    def _dual_analysis_done(self, slot, res):
        self.dual_candidates[slot] = res
        status = self.dual_status_a if slot == "A" else self.dual_status_b
        texts = self.dual_candidate_texts_a if slot == "A" else self.dual_candidate_texts_b
        for i in range(3):
            if i < len(res):
                x = res[i]
                texts[i].set(f"{slot} 후보 {i + 1}: {fmt(x.start)} ~ {fmt(x.end)} | 점수 {x.score:.3f} | BPM {x.bpm:.1f}")
            else:
                texts[i].set(f"{slot} 후보 {i + 1}: 없음")
        status.set(f"{slot}세트 TOP3 분석 완료")
        self._dual_log(f"{slot}세트 TOP3 분석 완료")

    def _dual_analysis_failed(self, slot, error):
        status = self.dual_status_a if slot == "A" else self.dual_status_b
        status.set(f"{slot}세트 분석 실패")
        self._dual_log(f"{slot}세트 분석 실패: {error}")

    def analyze(self):
        if not Path(self.audio.get()).exists():
            messagebox.showwarning("확인", "음원을 선택하세요.")
            return
        self.status.set("분석 중")
        self.p1.start(12)
        threading.Thread(target=self._analyze_worker, daemon=True).start()

    def _analyze_worker(self):
        try:
            vals, total = waveform_points(self.audio.get(), 1200)
            res = analyze_top_highlights(self.audio.get(), self.duration.get(), 3)
            self.after(0, lambda: self._analysis_done(vals, total, res))
        except Exception as e:
            self.after(0, lambda: (self.p1.stop(), self.status.set("분석 실패"), messagebox.showerror("오류", str(e))))

    def _analysis_done(self, vals, total, res):
        self.p1.stop()
        self.status.set("분석 완료")
        self.candidates = res
        self.wave_total = total
        for i in range(3):
            if i < len(res):
                x = res[i]
                self.candidate_texts[i].set(f"후보 {i + 1}: {fmt(x.start)} ~ {fmt(x.end)} | 점수 {x.score:.3f} | BPM {x.bpm:.1f}")
            else:
                self.candidate_texts[i].set(f"후보 {i + 1}: 없음")
        self.draw_wave(vals, total, res)

    def draw_wave(self, vals, total, res):
        c = self.canvas
        c.delete("all")
        c.update_idletasks()
        w = max(10, c.winfo_width())
        h = max(10, c.winfo_height())
        mid = h / 2
        n = len(vals)
        for x in range(min(w, n)):
            idx = int(x * n / w)
            amp = vals[idx] * (h * 0.42)
            c.create_line(x, mid - amp, x, mid + amp, fill="#94a3b8")
        colors = [DANGER, WARNING, ACCENT]
        fills = ["#ffe4ec", "#fff3c4", "#dbeafe"]
        for i, r in enumerate(res):
            x1 = r.start / total * w if total else 0
            x2 = r.end / total * w if total else 0
            c.create_rectangle(x1, 8, x2, h - 8, outline=colors[i], fill=fills[i], stipple="gray25", width=2)
            c.create_rectangle(x1 + 4, 12, x1 + 64, 34, fill=colors[i], outline="")
            c.create_text(x1 + 10, 23, text=f"TOP{i + 1}", anchor="w", fill="#ffffff", font=("Malgun Gothic", 9, "bold"))

    def preview(self):
        if not self.candidates:
            messagebox.showwarning("확인", "먼저 분석하세요.")
            return
        i = self.candidate_var.get()
        c = self.candidates[i]
        try:
            if self.preview_file and Path(self.preview_file).exists():
                try:
                    Path(self.preview_file).unlink()
                except Exception:
                    pass
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            extract_preview_wav(self.audio.get(), c.start, min(c.duration, 20.0), path)
            self.preview_file = path
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            self.status.set(f"TOP{i + 1} 미리듣기")
        except Exception as e:
            messagebox.showerror("미리듣기 오류", str(e))

    def stop_preview(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.status.set("미리듣기 정지")

    def _prepared_image(self, image_path, outdir, stem):
        if not self.auto_image.get():
            return image_path
        out = Path(outdir) / f"{stem}_VERTICAL.jpg"
        prepare_vertical_image(image_path, str(out), self.mode.get())
        return str(out)

    def render_selected(self):
        if not self.candidates or not Path(self.image.get()).exists():
            messagebox.showwarning("확인", "분석 후 이미지를 선택하세요.")
            return
        i = self.candidate_var.get()
        c = self.candidates[i]
        outdir = Path(self.output_dir.get())
        outdir.mkdir(parents=True, exist_ok=True)
        self.status.set("렌더링 중")
        self.p1.start(12)
        threading.Thread(target=self._render_worker, args=(c, i + 1), daemon=True).start()

    def _render_worker(self, c, idx):
        try:
            outdir = Path(self.output_dir.get())
            stem = Path(self.audio.get()).stem
            img = self._prepared_image(self.image.get(), outdir, stem)
            out = outdir / f"{stem}_SHORT_TOP{idx}_{int(c.duration)}s.mp4"
            render_short(
                self.audio.get(),
                img,
                str(out),
                c.start,
                c.duration,
                self.mode.get(),
                self.zoom.get(),
                self.fade.get(),
                use_nvenc=self.use_nvenc.get(),
                motion_pattern=self._motion_code(),
                subtitle_path=self.subtitle.get(),
                **self._render_options(),
            )
            if self.export_thumbnail.get():
                save_video_thumbnail(out)
            if self.auto_meta.get():
                md = make_metadata(stem, self.channel_name.get(), self.meta_template.get())
                save_metadata_txt(outdir, f"{stem}_TOP{idx}", md)
            validation = validate_social_video(out)
            message = f"{out}\n\n{self._format_compatibility_result(validation)}"
            done_status = f"완료 / SNS {self._compatibility_status(validation)}"
            self.after(0, lambda: (self.p1.stop(), self.status.set(done_status), messagebox.showinfo("완료", message)))
        except Exception as e:
            self.after(0, lambda: (self.p1.stop(), self.status.set("실패"), messagebox.showerror("오류", str(e))))

    def _safe_filename(self, name, fallback):
        raw = (name or fallback or "shorts").strip()
        safe = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in raw)
        safe = safe.strip(" .")
        return safe or "shorts"

    def _unique_output_path(self, folder, filename):
        out = Path(folder) / filename
        if out.suffix.lower() != ".mp4":
            out = out.with_suffix(".mp4")
        candidate = out
        n = 2
        while candidate.exists():
            candidate = out.with_name(f"{out.stem}_{n}{out.suffix}")
            n += 1
        return candidate

    def _dual_slots(self):
        return [
            {
                "label": "A세트",
                "slot": "A",
                "audio": self.dual_audio_a.get(),
                "image": self.dual_image_a.get(),
                "subtitle": self.dual_subtitle_a.get(),
                "output": self.dual_output_a.get(),
                "name": self.dual_name_a.get(),
                "status": self.dual_status_a,
            },
            {
                "label": "B세트",
                "slot": "B",
                "audio": self.dual_audio_b.get(),
                "image": self.dual_image_b.get(),
                "subtitle": self.dual_subtitle_b.get(),
                "output": self.dual_output_b.get(),
                "name": self.dual_name_b.get(),
                "status": self.dual_status_b,
            },
        ]

    def start_dual_render(self):
        slots = self._dual_slots()
        missing = []
        for item in slots:
            if not Path(item["audio"]).exists():
                missing.append(f"{item['label']} 음원")
            if not Path(item["image"]).exists():
                missing.append(f"{item['label']} 이미지")
            if not item["output"]:
                missing.append(f"{item['label']} 출력 폴더")
        if missing:
            messagebox.showwarning("확인", "필수 입력을 확인하세요.\n" + "\n".join(missing))
            return

        self.p_dual["value"] = 0
        self.dual_status_a.set("A세트 대기")
        self.dual_status_b.set("B세트 대기")
        self.status.set("숏츠 2개 제작 중")
        self._dual_log("듀얼 제작 시작")
        threading.Thread(target=self._dual_worker, args=(slots,), daemon=True).start()

    def _dual_worker(self, slots):
        done = 0
        generated = []
        for item in slots:
            try:
                self.after(0, lambda i=item: (i["status"].set(f"{i['label']} 분석/렌더 중"), self._dual_log(f"{i['label']} 분석/렌더 중")))
                result = self._render_dual_slot(item)
                generated.extend(result["files"])
                done += 1
                self.after(
                    0,
                    lambda i=item, d=done, p=result["video"], v=result["validation"]: (
                        i["status"].set(f"{i['label']} 완료: {Path(p).name} / SNS {self._compatibility_status(v)}"),
                        self.p_dual.configure(value=d),
                        self._dual_log(f"{i['label']} 완료: {p}\n{self._format_compatibility_result(v)}"),
                    ),
                )
            except Exception as e:
                self.after(
                    0,
                    lambda i=item, err=str(e): (
                        i["status"].set(f"{i['label']} 실패"),
                        self._dual_log(f"{i['label']} 실패: {err}"),
                    ),
                )
        if generated and self.zip_after_dual.get():
            try:
                zip_path = self._zip_dual_outputs(generated)
                generated.append(zip_path)
                self.after(0, lambda z=zip_path: self._dual_log(f"ZIP 완료: {z}"))
            except Exception as e:
                self.after(0, lambda err=str(e): self._dual_log(f"ZIP 실패: {err}"))
        self.after(0, lambda files=list(generated): (self._update_last_dual_outputs(files), self.status.set("숏츠 2개 제작 완료")))

    def _render_dual_slot(self, item):
        audio = item["audio"]
        image = item["image"]
        outdir = Path(item["output"])
        outdir.mkdir(parents=True, exist_ok=True)

        res = self.dual_candidates.get(item["slot"]) or analyze_top_highlights(audio, self.duration.get(), 3)
        if not res:
            raise RuntimeError("하이라이트를 찾지 못했습니다.")
        selected = self.dual_candidate_var_a.get() if item["slot"] == "A" else self.dual_candidate_var_b.get()
        selected = max(0, min(selected, len(res) - 1))
        candidate = res[selected]
        stem = self._safe_filename(item["name"], f"{Path(audio).stem}_{item['slot']}_SHORT")
        output = self._unique_output_path(outdir, f"{stem}.mp4")

        if self.auto_image.get():
            prepared = outdir / f"{stem}_{item['slot']}_VERTICAL.jpg"
            prepare_vertical_image(image, str(prepared), self.mode.get())
            image = str(prepared)

        subtitle = item["subtitle"] if item["subtitle"] and Path(item["subtitle"]).exists() else ""
        files = []
        render_short(
            audio,
            image,
            str(output),
            candidate.start,
            candidate.duration,
            self.mode.get(),
            self.zoom.get(),
            self.fade.get(),
            use_nvenc=self.use_nvenc.get(),
            motion_pattern=self._motion_code(),
            subtitle_path=subtitle,
            **self._render_options(),
        )
        files.append(str(output))
        if self.export_thumbnail.get():
            files.append(save_video_thumbnail(output))
        if self.auto_meta.get():
            md = make_metadata(Path(audio).stem, self.channel_name.get(), self.meta_template.get())
            files.append(save_metadata_txt(outdir, f"{output.stem}_{item['slot']}", md))
        validation = validate_social_video(output)
        return {"video": str(output), "files": files, "validation": validation}

    def _zip_dual_outputs(self, files):
        first_dir = Path(files[0]).parent
        zip_path = first_dir / f"{time.strftime('%Y%m%d')}_shorts_pack.zip"
        n = 2
        while zip_path.exists():
            zip_path = first_dir / f"{time.strftime('%Y%m%d')}_shorts_pack_{n}.zip"
            n += 1
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for file in files:
                p = Path(file)
                if p.exists():
                    z.write(p, p.name)
        return str(zip_path)

    def _dual_log(self, message):
        if hasattr(self, "dual_log"):
            self.dual_log.insert("end", message + "\n")
            self.dual_log.see("end")

    def _update_last_dual_outputs(self, files):
        videos = [str(p) for p in files if str(p).lower().endswith((".mp4", ".zip"))]
        self.last_dual_outputs_text.set("\n".join(videos) if videos else "듀얼 제작 결과가 없습니다.")

    def scan_batch(self):
        f = self.batch_input.get()
        if not f or not Path(f).exists():
            return
        self.batch_pairs = scan_pairs(f)
        for x in self.tree.get_children():
            self.tree.delete(x)
        for a, i, m in self.batch_pairs:
            self.tree.insert("", "end", values=(Path(a).name, Path(i).name if i else "", m))
        self.status.set(f"스캔 완료: {sum(1 for _, i, _ in self.batch_pairs if i)}/{len(self.batch_pairs)}")

    def start_batch(self):
        if not self.batch_pairs:
            self.scan_batch()
        pairs = [p for p in self.batch_pairs if p[1]]
        if not pairs:
            return
        self.cancel_requested = False
        total = len(pairs) * self.count_per_song.get()
        self.p2["maximum"] = total
        self.p2["value"] = 0
        threading.Thread(target=self._batch_worker, args=(pairs, total), daemon=True).start()

    def cancel_batch(self):
        self.cancel_requested = True
        self.status.set("현재 파일 완료 후 중지")

    def _batch_worker(self, pairs, total):
        outdir = Path(self.batch_output.get())
        outdir.mkdir(parents=True, exist_ok=True)
        done = 0
        for audio, image, _ in pairs:
            if self.cancel_requested:
                break
            try:
                res = analyze_top_highlights(audio, self.duration.get(), 3)
                stem = Path(audio).stem
                img = self._prepared_image(image, outdir, stem)
                for j, c in enumerate(res[: self.count_per_song.get()]):
                    if self.cancel_requested:
                        break
                    out = outdir / f"{stem}_SHORT_TOP{j + 1}_{self.duration.get()}s.mp4"
                    if out.exists() and self.skip_existing.get():
                        done += 1
                        self.after(0, lambda d=done, s=out.name: self._plog(d, total, f"건너뜀: {s}"))
                        continue
                    render_short(
                        audio,
                        img,
                        str(out),
                        c.start,
                        c.duration,
                        self.mode.get(),
                        self.zoom.get(),
                        self.fade.get(),
                        use_nvenc=self.use_nvenc.get(),
                        motion_pattern=self._motion_code(),
                        **self._render_options(),
                    )
                    if self.export_thumbnail.get():
                        save_video_thumbnail(out)
                    if self.auto_meta.get():
                        md = make_metadata(stem, self.channel_name.get(), self.meta_template.get())
                        save_metadata_txt(outdir, f"{stem}_TOP{j + 1}", md)
                    validation = validate_social_video(out)
                    compat = self._compatibility_status(validation)
                    issues = validation.get("issues") or []
                    detail = "" if not issues else " / " + "; ".join(issues[:2])
                    done += 1
                    self.after(0, lambda d=done, s=out.name, c=compat, x=detail: self._plog(d, total, f"완료: {s} / SNS {c}{x}"))
            except Exception as e:
                self.after(0, lambda a=Path(audio).name, err=str(e): self._log(f"실패: {a} / {err}"))
        self.after(0, lambda: self.status.set("중지됨" if self.cancel_requested else "일괄 완료"))

    def _plog(self, d, total, msg):
        self.p2["value"] = d
        self._log(f"[{d}/{total}] {msg}")

    def _log(self, s):
        self.log.insert("end", s + "\n")
        self.log.see("end")

    def save_log(self):
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if p:
            Path(p).write_text(self.log.get("1.0", "end"), encoding="utf-8")

    def make_zip(self, folder):
        if not folder or not Path(folder).exists():
            messagebox.showwarning("확인", "출력 폴더가 없습니다.")
            return
        try:
            z = zip_outputs(folder)
            messagebox.showinfo("ZIP 완료", z)
        except Exception as e:
            messagebox.showerror("오류", str(e))

    def save_settings(self):
        data = {
            "duration": self.duration.get(),
            "mode": self.mode.get(),
            "zoom": self.zoom.get(),
            "fade": self.fade.get(),
            "motion": self.motion.get(),
            "motion_intensity": self.motion_intensity.get(),
            "transition_interval": self.transition_interval.get(),
            "beat_reactivity": self.beat_reactivity.get(),
            "overlay_effect": self.overlay_effect.get(),
            "subtitle_position": self.subtitle_position.get(),
            "subtitle_size": self.subtitle_size.get(),
            "subtitle_style": self.subtitle_style.get(),
            "export_thumbnail": self.export_thumbnail.get(),
            "zip_after_dual": self.zip_after_dual.get(),
            "count_per_song": self.count_per_song.get(),
            "use_nvenc": self.use_nvenc.get(),
            "skip_existing": self.skip_existing.get(),
            "output_dir": self.output_dir.get(),
            "batch_output": self.batch_output.get(),
            "social_input_video": self.social_input_video.get(),
            "social_batch_folder": self.social_batch_folder.get(),
            "dual_audio_a": self.dual_audio_a.get(),
            "dual_image_a": self.dual_image_a.get(),
            "dual_subtitle_a": self.dual_subtitle_a.get(),
            "dual_output_a": self.dual_output_a.get(),
            "dual_name_a": self.dual_name_a.get(),
            "dual_audio_b": self.dual_audio_b.get(),
            "dual_image_b": self.dual_image_b.get(),
            "dual_subtitle_b": self.dual_subtitle_b.get(),
            "dual_output_b": self.dual_output_b.get(),
            "dual_name_b": self.dual_name_b.get(),
            "channel_name": self.channel_name.get(),
            "meta_template": self.meta_template.get(),
            "auto_meta": self.auto_meta.get(),
            "auto_image": self.auto_image.get(),
        }
        SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.status.set("설정 저장 완료")

    def load_settings(self):
        if not SETTINGS_FILE.exists():
            return
        try:
            d = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for k, v in d.items():
                if k == "motion":
                    self.motion.set(_choice_label(v, MOTION_LABEL_TO_CODE, MOTION_CODE_TO_LABEL, "감성형 랜덤", LEGACY_MOTION_LABELS))
                elif k == "motion_intensity":
                    self.motion_intensity.set(_choice_label(v, INTENSITY_LABEL_TO_CODE, INTENSITY_CODE_TO_LABEL, "중"))
                elif k == "beat_reactivity":
                    self.beat_reactivity.set(_choice_label(v, BEAT_LABEL_TO_CODE, BEAT_CODE_TO_LABEL, "끔"))
                elif k == "overlay_effect":
                    self.overlay_effect.set(_choice_label(v, OVERLAY_LABEL_TO_CODE, OVERLAY_CODE_TO_LABEL, "없음"))
                elif k == "subtitle_position":
                    self.subtitle_position.set(
                        _choice_label(v, SUBTITLE_POSITION_LABEL_TO_CODE, SUBTITLE_POSITION_CODE_TO_LABEL, "하단 안전영역")
                    )
                elif k == "subtitle_size":
                    self.subtitle_size.set(_choice_label(v, SUBTITLE_SIZE_LABEL_TO_CODE, SUBTITLE_SIZE_CODE_TO_LABEL, "보통"))
                elif k == "subtitle_style":
                    self.subtitle_style.set(_choice_label(v, SUBTITLE_STYLE_LABEL_TO_CODE, SUBTITLE_STYLE_CODE_TO_LABEL, "감성형"))
                elif k == "meta_template":
                    self.meta_template.set(v if v in META_TEMPLATES else "감성형")
                elif hasattr(self, k):
                    obj = getattr(self, k)
                    if hasattr(obj, "set"):
                        obj.set(v)
        except Exception:
            pass

    def destroy(self):
        if self.preview_after_id is not None:
            try:
                self.after_cancel(self.preview_after_id)
            except Exception:
                pass
        super().destroy()


if __name__ == "__main__":
    App().mainloop()
