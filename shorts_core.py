
from __future__ import annotations
import os, re, subprocess, tempfile, json, zipfile, shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List
import numpy as np
import librosa
import imageio_ffmpeg
from PIL import Image, ImageFilter

AUDIO_EXTS={".wav",".mp3",".m4a",".flac",".aac",".ogg",".opus"}
IMAGE_EXTS={".jpg",".jpeg",".png",".webp",".bmp"}

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
    kw={}
    if os.name=="nt":
        kw["creationflags"]=subprocess.CREATE_NO_WINDOW
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                     text=True,encoding="utf-8",errors="replace",**kw)
    if p.returncode!=0:
        raise RuntimeError(p.stderr[-5000:] or "FFmpeg 실행 오류")
    return p.stdout+p.stderr

def nvenc_available():
    try:
        p=subprocess.run([ffmpeg_path(),"-hide_banner","-encoders"],
                         stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                         text=True,encoding="utf-8",errors="replace")
        return "h264_nvenc" in (p.stdout+p.stderr)
    except Exception:
        return False

def decode_mono(audio_path,sr=22050):
    with tempfile.TemporaryDirectory(prefix="shortsmaker_") as td:
        wav=str(Path(td)/"audio.wav")
        _run([ffmpeg_path(),"-y","-hide_banner","-loglevel","error","-i",audio_path,
              "-vn","-ac","1","-ar",str(sr),"-c:a","pcm_s16le",wav])
        y,_=librosa.load(wav,sr=sr,mono=True)
    return y,sr

def waveform_points(audio_path, points=1200):
    y,sr=decode_mono(audio_path,22050)
    if len(y)==0:
        return np.zeros(points),0.0
    chunks=np.array_split(np.abs(y),points)
    vals=np.array([float(np.max(c)) if len(c) else 0.0 for c in chunks],dtype=float)
    m=vals.max() if vals.size else 1.0
    if m>0: vals/=m
    return vals, len(y)/sr

def extract_preview_wav(audio_path,start,duration,out_path):
    _run([ffmpeg_path(),"-y","-hide_banner","-loglevel","error",
          "-ss",f"{start:.3f}","-i",audio_path,"-t",f"{duration:.3f}",
          "-vn","-ac","2","-ar","44100","-c:a","pcm_s16le",out_path])
    return out_path

def analyze_top_highlights(audio_path,target_duration=45.0,top_n=3):
    target_duration=float(np.clip(target_duration,30.0,60.0))
    y,sr=decode_mono(audio_path,22050)
    total=len(y)/sr
    if total<=target_duration+2:
        return [HighlightResult(0.0,min(total,target_duration),min(total,target_duration),1.0,0.0,"짧은 곡 전체 사용")]

    hop=512
    rms=librosa.feature.rms(y=y,frame_length=2048,hop_length=hop)[0]
    onset=librosa.onset.onset_strength(y=y,sr=sr,hop_length=hop)
    S=np.abs(librosa.stft(y,n_fft=2048,hop_length=hop))
    flux=np.sqrt(np.maximum(0.0,np.diff(S,axis=1,prepend=S[:,:1])**2).mean(axis=0))

    def norm(v):
        v=np.asarray(v,float); lo,hi=np.percentile(v,5),np.percentile(v,95)
        return np.zeros_like(v) if hi<=lo+1e-12 else np.clip((v-lo)/(hi-lo),0,1)

    rn,on,fn=norm(rms),norm(onset),norm(flux)
    times=librosa.frames_to_time(np.arange(len(rn)),sr=sr,hop_length=hop)
    try:
        tempo,beats=librosa.beat.beat_track(y=y,sr=sr,hop_length=hop)
        bpm=float(np.atleast_1d(tempo)[0])
        bt=librosa.frames_to_time(beats,sr=sr,hop_length=hop)
    except Exception:
        bpm=0.0; bt=np.array([])

    max_start=total-target_duration
    margin=min(8.0,max(3.0,total*0.035))
    step=1.0 if total<240 else 2.0
    starts=np.arange(margin,max(margin+.1,max_start-margin),step)
    if not len(starts): starts=np.arange(0,max_start+.1,step)
    med=float(np.median(rn))
    scored=[]
    for st in starts:
        en=st+target_duration
        mask=(times>=st)&(times<en)
        if mask.sum()<8: continue
        rr,oo,ff=rn[mask],on[mask],fn[mask]
        energy=float(np.mean(rr)); p75=float(np.percentile(rr,75))
        rhythm=float(np.mean(oo)); spectral=float(np.mean(ff))
        dynamic=float(np.percentile(rr,90)-np.percentile(rr,20))
        stability=max(0.0,1.0-float(np.std(rr))*1.65)
        hook=(.58*energy+.42*p75)*(.65+.35*stability)
        quiet=max(0.0,(med*.72)-energy)*.45
        pos=(st+target_duration/2)/total
        pos_bonus=.045*(1.0-min(1.0,abs(pos-.58)/.58))
        edge_n=max(1,int(1.2*sr/hop))
        edge_bonus=.035*min(float(np.mean(rr[:edge_n])),float(np.mean(rr[-edge_n:])))
        score=.43*hook+.22*rhythm+.13*spectral+.12*dynamic+pos_bonus+edge_bonus-quiet
        scored.append((float(score),float(st)))
    scored.sort(reverse=True)

    picked=[]; sep=target_duration*.55
    for score,st in scored:
        if any(abs(st-p[1])<sep for p in picked): continue
        if bt.size:
            near=bt[np.abs(bt-st)<=1.35]
            if near.size:
                before=near[near<=st+.15]
                chosen=before[-1] if before.size else near[np.argmin(np.abs(near-st))]
                if 0<=chosen<=total-target_duration: st=float(chosen)
        st=max(0.0,min(st,total-target_duration))
        picked.append((score,st))
        if len(picked)>=top_n: break

    return [HighlightResult(round(st,3),round(st+target_duration,3),target_duration,
                            round(score,4),round(bpm,1),f"TOP {i}")
            for i,(score,st) in enumerate(picked,1)]

MOTION_PATTERNS=["zoom_in","zoom_out","pan_left","pan_right","gentle"]

def prepare_vertical_image(image_path,out_path,mode="fill",width=1080,height=1920):
    img=Image.open(image_path).convert("RGB")
    if mode=="blur":
        bg=img.copy()
        ratio=max(width/bg.width,height/bg.height)
        bg=bg.resize((int(bg.width*ratio),int(bg.height*ratio)),Image.LANCZOS)
        left=(bg.width-width)//2; top=(bg.height-height)//2
        bg=bg.crop((left,top,left+width,top+height)).filter(ImageFilter.GaussianBlur(28))
        fg=img.copy()
        ratio=min(width/fg.width,height/fg.height)
        fg=fg.resize((max(1,int(fg.width*ratio)),max(1,int(fg.height*ratio))),Image.LANCZOS)
        x=(width-fg.width)//2; y=(height-fg.height)//2
        bg.paste(fg,(x,y))
        out=bg
    else:
        ratio=max(width/img.width,height/img.height)
        img=img.resize((int(img.width*ratio),int(img.height*ratio)),Image.LANCZOS)
        left=(img.width-width)//2; top=(img.height-height)//2
        out=img.crop((left,top,left+width,top+height))
    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    out.save(out_path,quality=95)
    return out_path

def render_short(audio_path,image_path,output_path,start,duration,mode="fill",
                 zoom_pct=6.0,fade_sec=.5,fps=30,width=1080,height=1920,
                 use_nvenc=False,motion_pattern="zoom_in",subtitle_path=""):
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    duration=max(1.0,float(duration)); fade_sec=max(0.0,min(float(fade_sec),duration/4))
    frames=max(1,int(duration*fps))
    zmax=1.0+max(0.0,min(float(zoom_pct),15.0))/100.0

    if motion_pattern=="zoom_out":
        z=f"max({zmax:.5f}-({zmax-1:.8f}*on/{frames}),1.0)"; x="iw/2-(iw/zoom/2)"; y="ih/2-(ih/zoom/2)"
    elif motion_pattern=="pan_left":
        z=f"{zmax:.5f}"; x=f"(iw-iw/zoom)*(1-on/{frames})"; y="ih/2-(ih/zoom/2)"
    elif motion_pattern=="pan_right":
        z=f"{zmax:.5f}"; x=f"(iw-iw/zoom)*(on/{frames})"; y="ih/2-(ih/zoom/2)"
    elif motion_pattern=="gentle":
        z=f"min(1.0+({zmax-1:.8f}*on/{frames}),{zmax:.5f})"; x=f"(iw-iw/zoom)*(0.5+0.08*sin(on/{frames}*6.283))"; y="ih/2-(ih/zoom/2)"
    else:
        z=f"min(1.0+({zmax-1:.8f}*on/{frames}),{zmax:.5f})"; x="iw/2-(iw/zoom/2)"; y="ih/2-(ih/zoom/2)"

    if mode=="blur":
        vf=(f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=30:5[bg];"
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},format=yuv420p")
    else:
        vf=(f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},format=yuv420p")

    if subtitle_path and Path(subtitle_path).exists():
        sp=str(Path(subtitle_path).resolve()).replace("\\","/").replace(":","\\:")
        vf += f",subtitles='{sp}':force_style='FontName=Malgun Gothic,FontSize=18,Outline=2,Shadow=1,Alignment=2,MarginV=110'"

    if fade_sec>0:
        fo=max(0.0,duration-fade_sec)
        vf+=f",fade=t=in:st=0:d={fade_sec},fade=t=out:st={fo}:d={fade_sec}"
        af=f"afade=t=in:st=0:d={fade_sec},afade=t=out:st={fo}:d={fade_sec}"
    else:
        af="anull"

    cmd=[ffmpeg_path(),"-y","-hide_banner","-loglevel","error",
         "-loop","1","-framerate",str(fps),"-i",image_path,
         "-ss",f"{start:.3f}","-i",audio_path]
    if mode=="blur":
        cmd += ["-filter_complex",vf+"[v]","-map","[v]","-map","1:a:0"]
    else:
        cmd += ["-vf",vf,"-map","0:v:0","-map","1:a:0"]
    cmd += ["-af",af,"-t",f"{duration:.3f}","-r",str(fps)]
    if use_nvenc and nvenc_available():
        cmd += ["-c:v","h264_nvenc","-preset","p5","-cq","19","-b:v","0"]
    else:
        cmd += ["-c:v","libx264","-preset","medium","-crf","18","-profile:v","high","-level","4.1"]
    cmd += ["-c:a","aac","-b:a","256k","-ar","48000","-movflags","+faststart","-shortest",output_path]
    _run(cmd)
    return output_path

def _stem(p): return re.sub(r"\s+"," ",p.stem.lower().strip())
def _num(p):
    m=re.match(r"^\s*(\d{1,4})",p.stem)
    return (m.group(1).lstrip("0") or "0") if m else None

def scan_pairs(folder):
    base=Path(folder)
    audios=[p for p in base.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    images=[p for p in base.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    bystem={_stem(p):p for p in images}; bynum={}
    for p in images:
        n=_num(p)
        if n is not None and n not in bynum: bynum[n]=p
    out=[]
    for a in sorted(audios):
        img=bystem.get(_stem(a)); mt="동일 파일명"
        if img is None:
            n=_num(a)
            if n is not None:
                img=bynum.get(n)
                if img is not None: mt="앞번호 매칭"
        out.append((str(a),str(img) if img else "",mt if img else "이미지 없음"))
    return out

def make_metadata(track_name, channel_name, template_name="감성형"):
    title_base=Path(track_name).stem
    if template_name=="일본 ChillRap":
        title=f"{title_base} | Tokyo ChillRap #Shorts"
        desc=f"{title_base}\n\nTokyo night mood · ChillRap · Love Story\n🎧 {channel_name}\n\n#TokyoChillRap #ChillRap #Shorts"
        tags="#TokyoChillRap #ChillRap #JapanMusic #Shorts"
    elif template_name=="시니어 올드팝":
        title=f"{title_base} | 추억의 올드팝 #Shorts"
        desc=f"{title_base}\n\n추억을 깨우는 감성 올드팝 숏츠입니다.\n🎧 {channel_name}\n\n#올드팝 #7080 #추억의팝송 #Shorts"
        tags="#올드팝 #7080 #추억의팝송 #OldPop #Shorts"
    else:
        title=f"{title_base} | 감성 음악 #Shorts"
        desc=f"{title_base}\n\n잠시 머물러 듣는 감성 음악.\n🎧 {channel_name}\n\n#감성음악 #플레이리스트 #Shorts"
        tags="#감성음악 #플레이리스트 #MusicShorts #Shorts"
    return {"title":title,"description":desc,"hashtags":tags}

def save_metadata_txt(output_dir, base_name, metadata):
    p=Path(output_dir)/f"{base_name}_업로드정보.txt"
    text=f"제목\n{metadata['title']}\n\n설명\n{metadata['description']}\n\n해시태그\n{metadata['hashtags']}\n"
    p.write_text(text,encoding="utf-8")
    return str(p)

def zip_outputs(output_dir, zip_path=None):
    out=Path(output_dir)
    if zip_path is None:
        zip_path=str(out.parent/f"{out.name}_Shorts_Package.zip")
    with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED) as z:
        for p in out.rglob("*"):
            if p.is_file() and p.resolve()!=Path(zip_path).resolve():
                z.write(p,p.relative_to(out))
    return zip_path
