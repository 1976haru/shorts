# ShortsMaker Studio v0.6 Guide

## Light UI
v0.6 uses a bright work-oriented theme. The main background is light gray, panels and inputs are white, and borders use soft blue-gray lines. Buttons, tabs, text inputs, sliders, checkboxes, logs, TOP3 waveform markers, and preview panels are tuned for readability.

## Daily 2-Shorts Workflow
Use the `2개 동시 제작` tab when you want to create two shorts in one run.

1. Add `A세트` audio, image, optional SRT, output folder, and optional output name.
2. Add `B세트` audio, image, optional SRT, output folder, and optional output name.
3. Click `A TOP3 분석` and `B TOP3 분석` if you want to choose candidates manually.
4. Choose the common video, motion, and caption settings.
5. Click `숏츠 2개 제작`.

The dual workflow runs sequentially for stability. A and B use independent inputs, independent TOP3 candidate lists, and independent status messages. Output filename collisions are handled with numeric suffixes.

## Animation Off
The animation preset list includes `끔`. When selected, the final render disables zoom, pan, rotation, beat pulse, random motion, overlay, and fade. This keeps the same crop and scale for the full video.

## Motion Engine
Available presets include:

- 감성형 랜덤
- 천천히 줌인
- 천천히 줌아웃
- 왼쪽→오른쪽 팬
- 오른쪽→왼쪽 팬
- 위→아래
- 아래→위
- 대각선 이동
- 중앙 확대 + 약한 회전
- 후렴 강조형
- 랜덤 프리셋

Motion strength supports `약`, `중`, and `강`. Transition interval supports `3초`, `5초`, `8초`, and `10초`. Beat reaction supports `끔`, `약`, and `중`.

## Captions
The default caption position is `하단 안전영역`. Captions are smaller than v0.5 defaults and are intended to stay above mobile UI. Position, size, and style presets are available in the common caption settings.

When SRT is missing, rendering continues without subtitles. When SRT has English and Korean lines, the renderer keeps them in the lower safe area using FFmpeg subtitle wrapping and margins.

## Preview
The preview shows:

- current preview target: single, A, or B
- current animation preset
- caption position, size, and style
- safe-zone guide lines

The guide lines are preview-only and are not rendered into the final video.

## Thumbnail and ZIP
In the `2개 동시 제작` tab:

- `썸네일 자동 저장` extracts `*_thumb.jpg` from rendered videos.
- `완료 후 ZIP 패키지` creates a dated ZIP containing generated dual outputs.

Single and batch renders also create thumbnails when the thumbnail option is enabled.

## Legacy Settings
v0.5 settings load normally. Missing v0.6 fields use safe defaults:

- Theme: Light
- Animation: 감성형 랜덤
- Strength: 중
- Transition: 5초
- Beat reaction: 끔
- Overlay: 없음
- Caption: 하단 안전영역 / 작게 / 뮤직형

Existing output folders, NVENC, skip-existing, metadata, and image preprocessing settings are preserved when present.
