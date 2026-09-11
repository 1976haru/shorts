
from __future__ import annotations
import os, sys, random, threading, tempfile, subprocess, json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pygame
from tkinterdnd2 import TkinterDnD, DND_FILES
from shorts_core import *

APP_VERSION="0.5"
SETTINGS_FILE=Path(__file__).with_name("settings.json")

def fmt(sec):
    sec=max(0,float(sec)); m=int(sec//60); s=sec-m*60
    return f"{m:02d}:{s:05.2f}"

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"ShortsMaker Studio v{APP_VERSION}")
        self.geometry("1240x940"); self.minsize(1080,820)
        self.configure(bg="#151821")
        self._setup_style()

        self.duration=tk.IntVar(value=45)
        self.mode=tk.StringVar(value="fill")
        self.zoom=tk.DoubleVar(value=6.0)
        self.fade=tk.DoubleVar(value=.5)
        self.motion=tk.StringVar(value="랜덤")
        self.count_per_song=tk.IntVar(value=1)
        self.use_nvenc=tk.BooleanVar(value=False)
        self.skip_existing=tk.BooleanVar(value=True)
        self.status=tk.StringVar(value="준비")

        self.audio=tk.StringVar(); self.image=tk.StringVar(); self.subtitle=tk.StringVar()
        self.output_dir=tk.StringVar(value=str(Path.home()/"Videos"/"ShortsMaker"))
        self.batch_input=tk.StringVar()
        self.batch_output=tk.StringVar(value=str(Path.home()/"Videos"/"ShortsMaker_Batch"))
        self.channel_name=tk.StringVar(value="My Music Channel")
        self.meta_template=tk.StringVar(value="감성형")
        self.auto_meta=tk.BooleanVar(value=True)
        self.auto_image=tk.BooleanVar(value=True)

        self.candidates=[]; self.batch_pairs=[]; self.cancel_requested=False
        self.preview_file=None; self.wave_total=0.0
        self.load_settings()
        self._build()
        try: pygame.mixer.init()
        except: pass

    def _setup_style(self):
        s=ttk.Style(self)
        try:s.theme_use("clam")
        except:pass
        s.configure(".",background="#151821",foreground="#f4f5f7",fieldbackground="#232836")
        s.configure("TFrame",background="#151821")
        s.configure("TLabelframe",background="#151821",foreground="#f4f5f7")
        s.configure("TLabelframe.Label",background="#151821",foreground="#d7d9df")
        s.configure("TLabel",background="#151821",foreground="#f4f5f7")
        s.configure("TButton",padding=8,background="#2c3344",foreground="#ffffff")
        s.map("TButton",background=[("active","#3b455c")])
        s.configure("TNotebook",background="#151821")
        s.configure("TNotebook.Tab",padding=(16,8),background="#222735",foreground="#ddd")
        s.map("TNotebook.Tab",background=[("selected","#3a4358")],foreground=[("selected","#fff")])
        s.configure("Treeview",background="#202532",fieldbackground="#202532",foreground="#eee",rowheight=26)
        s.configure("Treeview.Heading",background="#30384a",foreground="#fff")
        s.configure("TCheckbutton",background="#151821",foreground="#eee")
        s.configure("TRadiobutton",background="#151821",foreground="#eee")

    def _build(self):
        top=ttk.Frame(self); top.pack(fill="x",padx=18,pady=(16,5))
        ttk.Label(top,text="ShortsMaker Studio",font=("Malgun Gothic",24,"bold")).pack(side="left")
        ttk.Label(top,text="v0.5",font=("Malgun Gothic",11,"bold")).pack(side="left",padx=8,pady=(9,0))
        ttk.Label(self,text="제작 → 자막 → 메타데이터 → ZIP 패키지까지 한 번에",font=("Malgun Gothic",10)).pack(anchor="w",padx=20)

        tabs=ttk.Notebook(self); tabs.pack(fill="both",expand=True,padx=14,pady=10)
        self.single=ttk.Frame(tabs); self.batch=ttk.Frame(tabs); self.publish=ttk.Frame(tabs)
        tabs.add(self.single,text="단일 제작"); tabs.add(self.batch,text="일괄 제작"); tabs.add(self.publish,text="업로드 준비")
        self._common(self.single); self._single_ui()
        self._common(self.batch); self._batch_ui()
        self._publish_ui()

        foot=ttk.Frame(self); foot.pack(fill="x",padx=18,pady=(0,10))
        ttk.Label(foot,text=f"NVENC: {'사용 가능' if nvenc_available() else '미감지'}").pack(side="left")
        ttk.Button(foot,text="설정 저장",command=self.save_settings).pack(side="left",padx=10)
        ttk.Label(foot,textvariable=self.status).pack(side="right")

    def _common(self,parent):
        f=ttk.LabelFrame(parent,text="공통 설정"); f.pack(fill="x",padx=10,pady=8)
        r=ttk.Frame(f); r.pack(fill="x",padx=8,pady=4)
        ttk.Label(r,text="길이",width=7).pack(side="left")
        for v in (30,45,60): ttk.Radiobutton(r,text=f"{v}초",variable=self.duration,value=v).pack(side="left",padx=3)
        ttk.Label(r,text="한 곡당",width=8).pack(side="left",padx=(18,0))
        ttk.Radiobutton(r,text="1개",variable=self.count_per_song,value=1).pack(side="left")
        ttk.Radiobutton(r,text="3개",variable=self.count_per_song,value=3).pack(side="left",padx=5)
        ttk.Label(r,text="화면",width=7).pack(side="left",padx=(18,0))
        ttk.Radiobutton(r,text="Fill",variable=self.mode,value="fill").pack(side="left")
        ttk.Radiobutton(r,text="Blur",variable=self.mode,value="blur").pack(side="left",padx=5)
        ttk.Label(r,text="움직임",width=8).pack(side="left",padx=(18,0))
        ttk.Combobox(r,textvariable=self.motion,state="readonly",
                     values=["랜덤","zoom_in","zoom_out","pan_left","pan_right","gentle"],width=12).pack(side="left")

        r2=ttk.Frame(f); r2.pack(fill="x",padx=8,pady=4)
        ttk.Label(r2,text="Zoom",width=7).pack(side="left")
        ttk.Scale(r2,from_=0,to=12,variable=self.zoom).pack(side="left",fill="x",expand=True)
        ttk.Label(r2,textvariable=self.zoom,width=5).pack(side="left")
        ttk.Label(r2,text="Fade",width=7).pack(side="left",padx=(12,0))
        ttk.Scale(r2,from_=0,to=2,variable=self.fade).pack(side="left",fill="x",expand=True)
        ttk.Label(r2,textvariable=self.fade,width=5).pack(side="left")
        ttk.Checkbutton(r2,text="NVENC",variable=self.use_nvenc).pack(side="left",padx=10)
        ttk.Checkbutton(r2,text="기존 파일 건너뛰기",variable=self.skip_existing).pack(side="left")

    def _pathrow(self,parent,label,var,cmd,drop=False):
        r=ttk.Frame(parent); r.pack(fill="x",pady=4)
        ttk.Label(r,text=label,width=12).pack(side="left")
        e=ttk.Entry(r,textvariable=var); e.pack(side="left",fill="x",expand=True,padx=5)
        ttk.Button(r,text="선택",command=cmd,width=9).pack(side="left")
        if drop:
            e.drop_target_register(DND_FILES)
            e.dnd_bind("<<Drop>>",lambda ev,v=var:self._drop(ev,v))
        return e

    def _drop(self,event,var):
        paths=self.tk.splitlist(event.data)
        if paths: var.set(paths[0])

    def _single_ui(self):
        b=ttk.Frame(self.single); b.pack(fill="both",expand=True,padx=10,pady=4)
        self._pathrow(b,"음원",self.audio,self.pick_audio,True)
        self._pathrow(b,"이미지",self.image,self.pick_image,True)
        self._pathrow(b,"자막 SRT",self.subtitle,self.pick_subtitle,True)
        self._pathrow(b,"출력 폴더",self.output_dir,self.pick_output)

        r=ttk.Frame(b); r.pack(fill="x",pady=6)
        ttk.Checkbutton(r,text="이미지 9:16 자동 전처리",variable=self.auto_image).pack(side="left")
        ttk.Button(r,text="TOP3 분석",command=self.analyze).pack(side="left",fill="x",expand=True,padx=4)
        ttk.Button(r,text="미리듣기",command=self.preview).pack(side="left",fill="x",expand=True,padx=4)
        ttk.Button(r,text="정지",command=self.stop_preview).pack(side="left",padx=4)
        ttk.Button(r,text="선택 후보 제작",command=self.render_selected).pack(side="left",fill="x",expand=True)

        wf=ttk.LabelFrame(b,text="파형 / TOP3 위치")
        wf.pack(fill="x",pady=6)
        self.canvas=tk.Canvas(wf,height=150,bg="#11141b",highlightthickness=0)
        self.canvas.pack(fill="x",expand=True,padx=8,pady=8)

        c=ttk.LabelFrame(b,text="하이라이트 TOP3"); c.pack(fill="x",pady=5)
        self.candidate_var=tk.IntVar(value=0)
        self.candidate_texts=[tk.StringVar(value=f"후보 {i+1}: 분석 전") for i in range(3)]
        for i in range(3):
            rr=ttk.Frame(c); rr.pack(fill="x",padx=6,pady=3)
            ttk.Radiobutton(rr,variable=self.candidate_var,value=i).pack(side="left")
            ttk.Label(rr,textvariable=self.candidate_texts[i]).pack(side="left")
        self.p1=ttk.Progressbar(b,mode="indeterminate"); self.p1.pack(fill="x",pady=8)

    def _batch_ui(self):
        b=ttk.Frame(self.batch); b.pack(fill="both",expand=True,padx=10,pady=4)
        self._pathrow(b,"입력 폴더",self.batch_input,self.pick_batch_input,True)
        self._pathrow(b,"출력 폴더",self.batch_output,self.pick_batch_output)
        r=ttk.Frame(b); r.pack(fill="x",pady=6)
        ttk.Button(r,text="파일 스캔",command=self.scan_batch).pack(side="left",fill="x",expand=True,padx=(0,4))
        ttk.Button(r,text="일괄 제작 시작",command=self.start_batch).pack(side="left",fill="x",expand=True,padx=4)
        ttk.Button(r,text="작업 중지",command=self.cancel_batch).pack(side="left",fill="x",expand=True,padx=4)
        ttk.Button(r,text="로그 저장",command=self.save_log).pack(side="left",fill="x",expand=True,padx=(4,0))

        box=ttk.LabelFrame(b,text="매칭 목록"); box.pack(fill="both",expand=True,pady=5)
        self.tree=ttk.Treeview(box,columns=("a","i","m"),show="headings",height=10)
        for col,txt,w in [("a","음원",380),("i","이미지",380),("m","매칭",110)]:
            self.tree.heading(col,text=txt); self.tree.column(col,width=w)
        self.tree.pack(fill="both",expand=True,side="left")
        sb=ttk.Scrollbar(box,orient="vertical",command=self.tree.yview); sb.pack(side="right",fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.p2=ttk.Progressbar(b,mode="determinate"); self.p2.pack(fill="x",pady=5)
        lf=ttk.LabelFrame(b,text="로그"); lf.pack(fill="both",expand=True,pady=5)
        self.log=tk.Text(lf,height=9,bg="#11141b",fg="#e7e9ee",insertbackground="#fff",wrap="word")
        self.log.pack(fill="both",expand=True,padx=5,pady=5)

    def _publish_ui(self):
        b=ttk.Frame(self.publish); b.pack(fill="both",expand=True,padx=14,pady=14)
        f=ttk.LabelFrame(b,text="채널/메타데이터 설정"); f.pack(fill="x",pady=6)
        r=ttk.Frame(f); r.pack(fill="x",padx=8,pady=6)
        ttk.Label(r,text="채널명",width=12).pack(side="left")
        ttk.Entry(r,textvariable=self.channel_name).pack(side="left",fill="x",expand=True,padx=5)
        ttk.Label(r,text="프리셋",width=8).pack(side="left",padx=(12,0))
        ttk.Combobox(r,textvariable=self.meta_template,state="readonly",
                     values=["감성형","시니어 올드팝","일본 ChillRap"],width=18).pack(side="left")
        ttk.Checkbutton(r,text="영상 제작 시 업로드정보 자동 생성",variable=self.auto_meta).pack(side="left",padx=12)

        z=ttk.LabelFrame(b,text="패키지"); z.pack(fill="x",pady=8)
        rr=ttk.Frame(z); rr.pack(fill="x",padx=8,pady=8)
        ttk.Button(rr,text="단일 출력 폴더 ZIP 만들기",command=lambda:self.make_zip(self.output_dir.get())).pack(side="left",fill="x",expand=True,padx=(0,4))
        ttk.Button(rr,text="배치 출력 폴더 ZIP 만들기",command=lambda:self.make_zip(self.batch_output.get())).pack(side="left",fill="x",expand=True,padx=(4,0))

        info=ttk.LabelFrame(b,text="v0.5 사용 흐름"); info.pack(fill="both",expand=True,pady=8)
        text=("1. 음원 + 이미지 선택\n"
              "2. TOP3 하이라이트 분석\n"
              "3. 필요하면 SRT 자막 추가\n"
              "4. 선택 후보 또는 배치 제작\n"
              "5. 업로드정보 TXT 자동 생성\n"
              "6. 결과 폴더를 ZIP으로 묶어 보관/전달\n\n"
              "※ 자막은 SRT 파일을 제공한 경우에만 영상에 삽입됩니다.")
        ttk.Label(info,text=text,justify="left",font=("Malgun Gothic",11)).pack(anchor="nw",padx=12,pady=12)

    def pick_audio(self):
        p=filedialog.askopenfilename(filetypes=[("Audio","*.wav *.mp3 *.m4a *.flac *.aac *.ogg *.opus")])
        if p:self.audio.set(p)
    def pick_image(self):
        p=filedialog.askopenfilename(filetypes=[("Image","*.jpg *.jpeg *.png *.webp *.bmp")])
        if p:self.image.set(p)
    def pick_subtitle(self):
        p=filedialog.askopenfilename(filetypes=[("Subtitle","*.srt"),("All","*.*")])
        if p:self.subtitle.set(p)
    def pick_output(self):
        p=filedialog.askdirectory()
        if p:self.output_dir.set(p)
    def pick_batch_input(self):
        p=filedialog.askdirectory()
        if p:self.batch_input.set(p)
    def pick_batch_output(self):
        p=filedialog.askdirectory()
        if p:self.batch_output.set(p)

    def motion_pick(self):
        return random.choice(MOTION_PATTERNS) if self.motion.get()=="랜덤" else self.motion.get()

    def analyze(self):
        if not Path(self.audio.get()).exists():
            messagebox.showwarning("확인","음원을 선택하세요."); return
        self.status.set("분석 중"); self.p1.start(12)
        threading.Thread(target=self._analyze_worker,daemon=True).start()

    def _analyze_worker(self):
        try:
            vals,total=waveform_points(self.audio.get(),1200)
            res=analyze_top_highlights(self.audio.get(),self.duration.get(),3)
            self.after(0,lambda:self._analysis_done(vals,total,res))
        except Exception as e:
            self.after(0,lambda:(self.p1.stop(),self.status.set("분석 실패"),messagebox.showerror("오류",str(e))))

    def _analysis_done(self,vals,total,res):
        self.p1.stop(); self.status.set("분석 완료"); self.candidates=res; self.wave_total=total
        for i in range(3):
            if i<len(res):
                x=res[i]; self.candidate_texts[i].set(f"후보 {i+1}: {fmt(x.start)} ~ {fmt(x.end)} | 점수 {x.score:.3f} | BPM {x.bpm:.1f}")
            else:self.candidate_texts[i].set(f"후보 {i+1}: 없음")
        self.draw_wave(vals,total,res)

    def draw_wave(self,vals,total,res):
        c=self.canvas; c.delete("all"); c.update_idletasks()
        w=max(10,c.winfo_width()); h=max(10,c.winfo_height()); mid=h/2
        n=len(vals)
        for x in range(min(w,n)):
            idx=int(x*n/w); amp=vals[idx]*(h*.42)
            c.create_line(x,mid-amp,x,mid+amp,fill="#7f8ba8")
        colors=["#ff6b6b","#ffd166","#70d6ff"]
        for i,r in enumerate(res):
            x1=r.start/total*w; x2=r.end/total*w
            c.create_rectangle(x1,8,x2,h-8,outline=colors[i],width=2)
            c.create_text(x1+6,14,text=f"TOP{i+1}",anchor="nw",fill=colors[i])

    def preview(self):
        if not self.candidates:
            messagebox.showwarning("확인","먼저 분석하세요."); return
        i=self.candidate_var.get()
        c=self.candidates[i]
        try:
            if self.preview_file and Path(self.preview_file).exists():
                try: Path(self.preview_file).unlink()
                except: pass
            fd,path=tempfile.mkstemp(suffix=".wav"); os.close(fd)
            extract_preview_wav(self.audio.get(),c.start,min(c.duration,20.0),path)
            self.preview_file=path
            pygame.mixer.music.load(path); pygame.mixer.music.play()
            self.status.set(f"TOP{i+1} 미리듣기")
        except Exception as e: messagebox.showerror("미리듣기 오류",str(e))

    def stop_preview(self):
        try: pygame.mixer.music.stop()
        except: pass
        self.status.set("미리듣기 정지")

    def _prepared_image(self, image_path, outdir, stem):
        if not self.auto_image.get():
            return image_path
        out=Path(outdir)/f"{stem}_VERTICAL.jpg"
        prepare_vertical_image(image_path,str(out),self.mode.get())
        return str(out)

    def render_selected(self):
        if not self.candidates or not Path(self.image.get()).exists():
            messagebox.showwarning("확인","분석 후 이미지를 선택하세요."); return
        i=self.candidate_var.get(); c=self.candidates[i]
        outdir=Path(self.output_dir.get()); outdir.mkdir(parents=True,exist_ok=True)
        self.status.set("렌더링 중"); self.p1.start(12)
        threading.Thread(target=self._render_worker,args=(c,i+1),daemon=True).start()

    def _render_worker(self,c,idx):
        try:
            outdir=Path(self.output_dir.get()); stem=Path(self.audio.get()).stem
            img=self._prepared_image(self.image.get(),outdir,stem)
            out=outdir/f"{stem}_SHORT_TOP{idx}_{int(c.duration)}s.mp4"
            render_short(self.audio.get(),img,str(out),c.start,c.duration,
                         self.mode.get(),self.zoom.get(),self.fade.get(),
                         use_nvenc=self.use_nvenc.get(),motion_pattern=self.motion_pick(),
                         subtitle_path=self.subtitle.get())
            if self.auto_meta.get():
                md=make_metadata(stem,self.channel_name.get(),self.meta_template.get())
                save_metadata_txt(outdir,f"{stem}_TOP{idx}",md)
            self.after(0,lambda:(self.p1.stop(),self.status.set("완료"),messagebox.showinfo("완료",str(out))))
        except Exception as e:
            self.after(0,lambda:(self.p1.stop(),self.status.set("실패"),messagebox.showerror("오류",str(e))))

    def scan_batch(self):
        f=self.batch_input.get()
        if not f or not Path(f).exists(): return
        self.batch_pairs=scan_pairs(f)
        for x in self.tree.get_children(): self.tree.delete(x)
        for a,i,m in self.batch_pairs:
            self.tree.insert("","end",values=(Path(a).name,Path(i).name if i else "",m))
        self.status.set(f"스캔 완료: {sum(1 for _,i,_ in self.batch_pairs if i)}/{len(self.batch_pairs)}")

    def start_batch(self):
        if not self.batch_pairs:self.scan_batch()
        pairs=[p for p in self.batch_pairs if p[1]]
        if not pairs:return
        self.cancel_requested=False
        total=len(pairs)*self.count_per_song.get()
        self.p2["maximum"]=total; self.p2["value"]=0
        threading.Thread(target=self._batch_worker,args=(pairs,total),daemon=True).start()

    def cancel_batch(self):
        self.cancel_requested=True; self.status.set("현재 파일 완료 후 중지")

    def _batch_worker(self,pairs,total):
        outdir=Path(self.batch_output.get()); outdir.mkdir(parents=True,exist_ok=True)
        done=0
        for audio,image,_ in pairs:
            if self.cancel_requested: break
            try:
                res=analyze_top_highlights(audio,self.duration.get(),3)
                stem=Path(audio).stem
                img=self._prepared_image(image,outdir,stem)
                for j,c in enumerate(res[:self.count_per_song.get()]):
                    if self.cancel_requested: break
                    out=outdir/f"{stem}_SHORT_TOP{j+1}_{self.duration.get()}s.mp4"
                    if out.exists() and self.skip_existing.get():
                        done+=1; self.after(0,lambda d=done,s=out.name:self._plog(d,total,f"건너뜀: {s}")); continue
                    render_short(audio,img,str(out),c.start,c.duration,self.mode.get(),self.zoom.get(),self.fade.get(),
                                 use_nvenc=self.use_nvenc.get(),motion_pattern=self.motion_pick())
                    if self.auto_meta.get():
                        md=make_metadata(stem,self.channel_name.get(),self.meta_template.get())
                        save_metadata_txt(outdir,f"{stem}_TOP{j+1}",md)
                    done+=1; self.after(0,lambda d=done,s=out.name:self._plog(d,total,f"완료: {s}"))
            except Exception as e:
                self.after(0,lambda a=Path(audio).name,err=str(e):self._log(f"실패: {a} / {err}"))
        self.after(0,lambda:self.status.set("중지됨" if self.cancel_requested else "일괄 완료"))

    def _plog(self,d,total,msg):
        self.p2["value"]=d; self._log(f"[{d}/{total}] {msg}")
    def _log(self,s):
        self.log.insert("end",s+"\n"); self.log.see("end")
    def save_log(self):
        p=filedialog.asksaveasfilename(defaultextension=".txt",filetypes=[("Text","*.txt")])
        if p: Path(p).write_text(self.log.get("1.0","end"),encoding="utf-8")

    def make_zip(self,folder):
        if not folder or not Path(folder).exists():
            messagebox.showwarning("확인","출력 폴더가 없습니다."); return
        try:
            z=zip_outputs(folder)
            messagebox.showinfo("ZIP 완료",z)
        except Exception as e:
            messagebox.showerror("오류",str(e))

    def save_settings(self):
        data={"duration":self.duration.get(),"mode":self.mode.get(),"zoom":self.zoom.get(),
              "fade":self.fade.get(),"motion":self.motion.get(),"count_per_song":self.count_per_song.get(),
              "use_nvenc":self.use_nvenc.get(),"skip_existing":self.skip_existing.get(),
              "output_dir":self.output_dir.get(),"batch_output":self.batch_output.get(),
              "channel_name":self.channel_name.get(),"meta_template":self.meta_template.get(),
              "auto_meta":self.auto_meta.get(),"auto_image":self.auto_image.get()}
        SETTINGS_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        self.status.set("설정 저장 완료")

    def load_settings(self):
        if not SETTINGS_FILE.exists(): return
        try:
            d=json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for k,v in d.items():
                if hasattr(self,k):
                    obj=getattr(self,k)
                    if hasattr(obj,"set"): obj.set(v)
        except: pass

if __name__=="__main__":
    App().mainloop()
