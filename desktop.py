"""Native desktop floating assistant; no browser or HTTP service is required."""
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime,timedelta,timezone

from controller import Controller, VERSION
from experiment import GUIDE
from llm import Chat, ModelSettings
from desktop_widgets import BG,PAPER,INK,GREEN,MUTED,LINE,FONT,ScrollPage,SettingsDialog,button,label,replace_text
from runtime_paths import default_data_dir

ROOT=Path(__file__).resolve().parent
HARDWARE_LABELS={"vplus_enabled":"V+ 使能","vplus_setting":"V+ 设定值 / V（非实测）",
                 "vminus_enabled":"V− 使能","dio_running":"Digital I/O 运行",
                 "dio2_direction":"DIO2 方向 / 原始值","dio2_input":"DIO2 当前输入",
                 "logic_sample_rate":"逻辑采样率 / S/s","logic_buffer_size":"逻辑缓冲点数"}


def display_time(value):
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")+" 北京时间"


class DesktopApp:
    def __init__(self,root,controller=None,settings=None,chat=None):
        self.root=root
        self.controller=controller or Controller(default_data_dir())
        self.settings=settings or ModelSettings()
        self.chat=chat or Chat(self.controller,self.settings)
        self.inbox=queue.Queue()
        self.busy=False;self.closed=False;self.collapsed=False;self.settings_dialog=None;self.worker=None
        self.job_serial=0;self.task_cancel=None
        self.step=0;self.shown_run=None;self.expanded_geometry=None
        self.root.title(f"模电实验 Copilot · 桌面浮窗 v{VERSION}")
        self.root.configure(bg=BG);self.root.geometry("430x640")
        self.root.minsize(410,620)
        self.root.protocol("WM_DELETE_WINDOW",self.close)
        style=ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TNotebook",background=BG,borderwidth=0)
        style.configure("TNotebook.Tab",font=(FONT,10),padding=(17,8),background="#e8eee1")
        style.map("TNotebook.Tab",background=[("selected",PAPER)],foreground=[("selected",GREEN)])
        style.configure("Treeview",font=(FONT,9),rowheight=27,background=PAPER,fieldbackground=PAPER)
        style.configure("Treeview.Heading",font=(FONT,9),background="#edf2e7")
        self._header()
        self.content=tk.Frame(root,bg=BG)
        self.content.pack(fill="both",expand=True,padx=12,pady=(0,10))
        self.tabs=ttk.Notebook(self.content);self.tabs.pack(fill="both",expand=True)
        self.chat_page=tk.Frame(self.tabs,bg=PAPER)
        self.lab_page=ScrollPage(self.tabs)
        self.hardware_page=tk.Frame(self.tabs,bg=PAPER)
        self.tabs.add(self.chat_page,text="实验助手");self.tabs.add(self.lab_page,text="步骤与模拟");self.tabs.add(self.hardware_page,text="真实仪器")
        self._chat_page();self._lab_page();self._hardware_page()
        label(self.content,"真实供电与输出需具体确认；本版本仍锁定全部真实写操作。",size=8,color=MUTED,anchor="w",wraplength=370,justify="left").pack(fill="x",pady=(7,0))
        self.pump_id=self.root.after(80,self._pump)
        self.refresh()

    def _header(self):
        head=tk.Frame(self.root,bg=GREEN,padx=14,pady=10);head.pack(fill="x")
        label(head,"∧  模电实验 Copilot",size=12,color=PAPER,bg=GREEN).pack(side="left")
        self.stop_button=button(head,"■ 停止本地",self.stop,danger=True);self.stop_button.pack(side="right")
        self.pinned=tk.BooleanVar(self.root,True)
        tk.Checkbutton(head,text="置顶",variable=self.pinned,command=self.apply_pin,bg=GREEN,fg=PAPER,
                       selectcolor=GREEN,activebackground=GREEN,activeforeground=PAPER,font=(FONT,9)).pack(side="right",padx=8)
        self.apply_pin()
        bar=tk.Frame(self.root,bg=BG,padx=14,pady=8);bar.pack(fill="x")
        self.connection=tk.StringVar(self.root,"尚未检查真实连接")
        label(bar,textvariable=self.connection,size=9,color=GREEN,anchor="w").pack(side="left",fill="x",expand=True)
        self.collapse_button=button(bar,"收起 ▴",self.toggle_collapsed);self.collapse_button.pack(side="right")
        self.reset_button=button(bar,"恢复演示",self.reset)

    def _chat_page(self):
        page=self.chat_page
        label(page,"中文对话 · 真实只读检查 · 本地模拟",size=10,color=GREEN,anchor="w").pack(fill="x",padx=14,pady=(13,7))
        row=tk.Frame(page,bg=PAPER);row.pack(fill="x",padx=14,pady=5)
        for text,prompt in (("检查真实状态","检查真实 Scopy 状态"),("接线指导","接线怎么做"),("运行模拟","运行模拟")):
            button(row,text,lambda p=prompt:self.send(p)).pack(side="left",padx=(0,6))
        box=tk.Frame(page,bg=PAPER);box.pack(fill="both",expand=True,padx=14,pady=7)
        self.transcript=tk.Text(box,wrap="word",font=(FONT,10),bg="#f6f8f1",fg=INK,relief="flat",padx=12,pady=12,state="disabled",height=6)
        scroll=ttk.Scrollbar(box,command=self.transcript.yview);self.transcript.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right",fill="y");self.transcript.pack(fill="both",expand=True)
        self.transcript.tag_configure("assistant",foreground=GREEN,spacing1=10,spacing3=9)
        self.transcript.tag_configure("user",foreground="#956332",spacing1=10,spacing3=8)
        self.transcript.tag_configure("error",foreground="#a3483d",spacing1=10,spacing3=8)
        self.append("已切换为原生桌面浮窗。\n可以直接说「检查真实 Scopy 状态」，每次会发起新的只读检查。离线模式提供固定教程；自由问答请在模型设置中输入本机 API Key。\n\n供电和输出仍保持锁定。","assistant")
        controls=tk.Frame(page,bg=PAPER);controls.pack(fill="x",padx=14,pady=4)
        self.mode=tk.StringVar(self.root,"离线教程")
        mode=ttk.Combobox(controls,textvariable=self.mode,values=("离线教程","外部模型 API"),state="readonly",width=16)
        mode.pack(side="left");mode.bind("<<ComboboxSelected>>",lambda e:self.update_model_label())
        button(controls,"模型设置",self.open_settings).pack(side="right")
        self.model_note=tk.StringVar(self.root,"")
        label(page,textvariable=self.model_note,size=8,color=MUTED,anchor="w").pack(fill="x",padx=14)
        self.chat_input=tk.Text(page,height=3,wrap="word",font=(FONT,10),bg=PAPER,fg=INK,highlightthickness=1,highlightbackground=LINE,relief="flat",padx=8,pady=7)
        self.chat_input.pack(fill="x",padx=14,pady=(7,5))
        self.chat_input.bind("<Control-Return>",lambda e:(self.send(),"break")[1])
        bottom=tk.Frame(page,bg=PAPER);bottom.pack(fill="x",padx=14,pady=(0,12))
        self.task_note=tk.StringVar(self.root,"Ctrl+Enter 发送；原始波形留在本机")
        label(bottom,textvariable=self.task_note,size=8,color=MUTED,anchor="w").pack(side="left",fill="x",expand=True)
        self.send_button=button(bottom,"发送 ↑",self.send,primary=True);self.send_button.pack(side="right")
        self.update_model_label()

    def _lab_page(self):
        page=self.lab_page.body
        guide=tk.Frame(page,bg=PAPER,padx=14,pady=12);guide.pack(fill="x",pady=(0,10))
        self.step_title=tk.StringVar(self.root)
        label(guide,textvariable=self.step_title,size=12,color=GREEN,anchor="w").pack(fill="x")
        self.step_text=tk.StringVar(self.root)
        label(guide,textvariable=self.step_text,size=10,wraplength=350,justify="left",anchor="w").pack(fill="x",pady=10)
        nav=tk.Frame(guide,bg=PAPER);nav.pack(fill="x")
        button(nav,"← 上一步",lambda:self.show_step(-1)).pack(side="left")
        button(nav,"下一步 →",lambda:self.show_step(1)).pack(side="right")
        self.show_step(0)
        config=tk.Frame(page,bg=PAPER,padx=14,pady=12);config.pack(fill="x",pady=(0,10))
        label(config,"模拟采样 · 不控制硬件",size=11,color=GREEN,anchor="w").pack(fill="x")
        fields=tk.Frame(config,bg=PAPER);fields.pack(fill="x",pady=9)
        self.params={}
        for i,(name,title,value) in enumerate((("frequency","随机码率","100 Hz"),("sample_rate","采样率","100 kS/s"),("samples","点数","20000"))):
            cell=tk.Frame(fields,bg=PAPER);cell.grid(row=0,column=i,sticky="ew",padx=(0,8));fields.columnconfigure(i,weight=1)
            label(cell,title,size=9,color=MUTED,anchor="w").pack(fill="x")
            self.params[name]=tk.StringVar(self.root,value)
            ttk.Entry(cell,textvariable=self.params[name],width=13).pack(fill="x",pady=3)
        row=tk.Frame(config,bg=PAPER);row.pack(fill="x")
        self.fault=tk.StringVar(self.root,"正常与门")
        ttk.Combobox(row,textvariable=self.fault,values=("正常与门","输出始终为0","误接与非门"),state="readonly",width=14).pack(side="left")
        self.run_button=button(row,"运行模拟并判读",self.run_simulation,primary=True);self.run_button.pack(side="right")
        result=tk.Frame(page,bg=PAPER,padx=14,pady=12);result.pack(fill="x")
        self.result_note=tk.StringVar(self.root,"等待模拟记录。模拟不能证明实际电路有效。")
        label(result,textvariable=self.result_note,size=10,color=GREEN,wraplength=350,justify="left",anchor="w").pack(fill="x")
        self.wave=tk.Canvas(result,height=155,bg="#f6f8f1",highlightthickness=0)
        self.wave.pack(fill="x",pady=10);self.wave.bind("<Configure>",lambda e:self.draw_wave())
        self.truth=ttk.Treeview(result,columns=("a","b","y","n","check"),show="headings",height=4)
        for name,title,width in (("a","A",35),("b","B",35),("y","期望Y",65),("n","稳态点数",90),("check","判读",120)):
            self.truth.heading(name,text=title);self.truth.column(name,width=width,anchor="center")
        self.truth.pack(fill="x")
        files=tk.Frame(result,bg=PAPER);files.pack(fill="x",pady=(10,0))
        button(files,"打开证据目录",self.open_evidence).pack(side="left")
        label(files,"CSV + 判读 JSON + SHA256",size=8,color=MUTED).pack(side="right")

    def _hardware_page(self):
        page=self.hardware_page
        label(page,"真实只读检查",size=13,color=GREEN,anchor="w").pack(fill="x",padx=15,pady=(15,5))
        label(page,"通过官方 Scopy MCP 读取固定属性。\n每次点击或模型调用都会重新检查，不启用任何输出。",size=9,color=MUTED,wraplength=350,justify="left",anchor="w").pack(fill="x",padx=15)
        self.probe_button=button(page,"立即检查真实状态（只读）",self.check_hardware,primary=True)
        self.probe_button.pack(anchor="w",padx=15,pady=12)
        self.hardware_text=tk.Text(page,wrap="word",height=8,font=(FONT,10),bg="#f6f8f1",fg=INK,relief="flat",padx=12,pady=10,state="disabled")
        self.hardware_text.pack(fill="both",expand=True,padx=15,pady=(0,9))
        label(page,"操作记录（不记录对话和密钥）",size=9,color=MUTED,anchor="w").pack(fill="x",padx=15)
        self.events_text=tk.Text(page,wrap="word",height=5,font=(FONT,8),bg=PAPER,fg=MUTED,relief="flat",state="disabled")
        self.events_text.pack(fill="x",padx=15,pady=(3,12))

    def apply_pin(self):
        self.root.attributes("-topmost",self.pinned.get())

    def toggle_collapsed(self):
        if not self.collapsed:
            self.expanded_geometry=self.root.geometry()
            self.content.pack_forget();self.root.minsize(390,110)
            self.root.geometry("400x110");self.collapse_button.configure(text="展开 ▾")
        else:
            self.content.pack(fill="both",expand=True,padx=12,pady=(0,10))
            self.root.minsize(410,620);self.root.geometry(self.expanded_geometry or "430x640")
            self.collapse_button.configure(text="收起 ▴")
        self.collapsed=not self.collapsed

    def append(self,text,kind="assistant"):
        self.transcript.configure(state="normal")
        self.transcript.insert("end",("你\n" if kind=="user" else "操作未完成\n" if kind=="error" else "助手\n")+text+"\n\n",kind)
        self.transcript.configure(state="disabled");self.transcript.see("end")

    def update_model_label(self):
        s=self.settings.public()
        self.model_note.set((s["model"]+" · "+("本次密钥已配置" if s["has_key"] else "请先设置本机密钥")+" · 对话与摘要会发往所设API") if self.mode.get()=="外部模型 API" else "离线固定教程 · 真实只读检查无需模型Key")

    def open_settings(self):
        if self.settings_dialog is not None:
            self.settings_dialog.window.lift();return self.settings_dialog
        self.settings_dialog=SettingsDialog(self)
        return self.settings_dialog

    def submit(self,kind,operation):
        if self.busy or self.closed:return
        cancel=threading.Event()
        with self.controller.lock:
            generation=self.controller.generation
            try:self.controller.check_turn(generation,cancel)
            except InterruptedError as error:self.append(str(error),"error");return
        self.job_serial+=1;job=self.job_serial;self.task_cancel=cancel
        self.busy=True;self.task_note.set("正在处理… 停止按钮可随时取消本地任务")
        self.refresh()
        def work():
            try:
                self.controller.check_turn(generation,cancel)
                result=operation(generation,cancel)
                self.controller.check_turn(generation,cancel)
                self.inbox.put((job,kind,generation,True,result))
            except (ValueError,InterruptedError) as error:self.inbox.put((job,kind,generation,False,str(error)))
            except Exception:self.inbox.put((job,kind,generation,False,"本地操作失败，未重试或恢复输出。"))
        self.worker=threading.Thread(target=work,daemon=True)
        self.worker.start()

    def send(self,text=None):
        if self.busy:return
        message=text if text is not None else self.chat_input.get("1.0","end").strip()
        if not message:return
        mode="api" if self.mode.get()=="外部模型 API" else "offline"
        self.chat_input.delete("1.0","end");self.append(message,"user")
        self.submit("chat",lambda g,c:self.chat.reply(message,mode,generation=g,cancelled=c))

    def check_hardware(self):
        self.submit("probe",lambda g,c:self.controller.check_hardware(cancelled=c,generation=g))

    def run_simulation(self):
        if self.busy:return
        values={name:var.get() for name,var in self.params.items()}
        try:values["samples"]=int(values["samples"])
        except ValueError:self.append("采样点数必须为整数。","error");return
        fault={"正常与门":"none","输出始终为0":"stuck_low","误接与非门":"nand"}[self.fault.get()]
        self.submit("simulation",lambda g,c:self.controller.run_simulation(values,fault,cancelled=c,generation=g))

    def stop(self):
        if self.task_cancel:self.task_cancel.set()
        result=self.controller.stop();self.chat.cancel()
        self.task_note.set("已停止本地任务；未向实际设备发送停机命令")
        self.append(result["message"]);self.refresh()

    def reset(self):
        try:self.controller.reset();self.task_note.set("已恢复本地任务；未恢复实际输出")
        except ValueError as error:self.append(str(error),"error")
        self.refresh()

    def show_step(self,delta):
        self.step=max(0,min(len(GUIDE)-1,self.step+delta))
        self.step_title.set(f"{self.step+1:02d} / {len(GUIDE):02d}  {GUIDE[self.step]['title']}")
        self.step_text.set(GUIDE[self.step]["text"])

    def draw_wave(self):
        self.wave.delete("all")
        r=self.controller.last
        if not r:return
        p=r["preview"];width=max(350,self.wave.winfo_width())-65;n=p["points"]
        for i,(name,key,color) in enumerate((("A","a",GREEN),("B","b","#a68b45"),("Y","y","#367c98"))):
            low=36+i*44;high=low-20
            self.wave.create_text(17,low-10,text=name,fill=color,font=(FONT,10))
            self.wave.create_line(42,low,42+width,low,fill=LINE)
            points=p[key];coords=[42,high if points[0] else low]
            for j in range(1,n):
                if points[j]!=points[j-1]:
                    x=42+width*j/n;coords.extend((x,high if points[j-1] else low,x,high if points[j] else low))
            coords.extend((42+width,high if points[-1] else low));self.wave.create_line(*coords,fill=color,width=2)
        self.wave.create_text(42,147,text="0 ms",anchor="w",fill=MUTED,font=(FONT,8))
        self.wave.create_text(42+width,147,text=f"{n/p['sample_rate']*1000:g} ms · 模拟",anchor="e",fill=MUTED,font=(FONT,8))

    def refresh(self):
        s=self.controller.status();h=s["hardware"]
        self.connection.set("已停止本地任务" if s["stopped"] else "正在真实只读检查…" if h.get("pending") else "● 最近只读检查成功 · 写操作锁定" if h.get("connected") else "○ 真实连接尚未核实 · 写操作锁定")
        for b in (self.send_button,self.run_button,self.probe_button):b.configure(state="disabled" if self.busy or s["stopped"] else "normal")
        if s["stopped"]:self.reset_button.pack(side="right",padx=5)
        else:self.reset_button.pack_forget()
        lines=[h.get("message","尚未检查")]
        if h.get("time"):lines.extend(("", "最近检查："+display_time(h["time"]),"以下为最近检查快照，重新检查才会刷新。"))
        for key,value in h.get("snapshot",{}).items():
            if key=="vplus_setting":
                try:value=f"{float(value):.6g}"
                except (ValueError,TypeError):pass
            elif key in ("vplus_enabled","vminus_enabled","dio_running") and value in ("true","false"):
                value="开启" if value=="true" else "关闭"
            lines.append(f"{HARDWARE_LABELS.get(key,key)}：{value}")
        lines.extend(("","未执行真实采样、参数设置或输出使能。","设定值不等于实测电压；未确认接线。"))
        replace_text(self.hardware_text,"\n".join(lines))
        replace_text(self.events_text,"\n".join(f"{display_time(x['time'])[11:19]}  {x['event']}" for x in s["events"][-7:]))
        r=s["last"]
        if r and r["id"]!=self.shown_run:
            self.shown_run=r["id"];summary=r["summary"]
            verdict={"PASS":"符合与逻辑","FAIL":"逻辑不符","INCOMPLETE":"覆盖不足"}[summary["verdict"]]
            self.result_note.set(f"模拟证据 · {verdict}｜覆盖 {summary['coverage']}/4｜稳态错误 {summary['errors']} 点\n{summary['samples']} 点；输入边沿排除 {summary['excluded_edges']} 点；模拟配置回读一致。")
            self.truth.delete(*self.truth.get_children())
            for row in summary["rows"]:
                self.truth.insert("","end",values=(row["a"],row["b"],row["expected"],row["count"],"未覆盖" if not row["count"] else f"{row['errors']}点不符" if row["errors"] else "符合"))
            self.draw_wave()

    def _pump(self):
        if self.closed:return
        while True:
            try:job,kind,generation,ok,result=self.inbox.get_nowait()
            except queue.Empty:break
            if job!=self.job_serial:continue
            self.busy=False
            if generation!=self.controller.generation or (self.task_cancel and self.task_cancel.is_set()):
                self.task_note.set("已丢弃先前取消任务的回执")
                self.task_cancel=None
                continue
            if not ok:self.append(result,"error")
            elif kind=="chat":self.append(result["text"])
            elif kind=="probe":self.append(result.get("message","只读检查完成"));self.tabs.select(self.hardware_page)
            elif kind=="simulation":self.tabs.select(self.lab_page);self.append("模拟完成，原始数据与判读已保存。本次未采集硬件数据。")
            self.task_note.set("已停止本地任务" if self.controller.stopped.is_set() else "处理结束 · 原始波形留在本机")
            self.task_cancel=None
        self.refresh()
        self.pump_id=self.root.after(150,self._pump)

    def open_evidence(self):
        if not self.controller.last:self.append("尚无记录，请先运行模拟。");return
        folder=self.controller.data_dir/"runs"/self.controller.last["id"]
        if os.name=="nt":os.startfile(str(folder.resolve()))

    def close(self):
        if self.closed:return
        if self.task_cancel:self.task_cancel.set()
        self.closed=True;self.controller.stop();self.chat.cancel()
        if self.worker is not None and self.worker.is_alive():
            self.worker.join(timeout=4)
        if self.settings_dialog is not None:self.settings_dialog.close()
        self.settings.update({"clear_key":True})
        self.root.after_cancel(self.pump_id)
        self.root.destroy()


def main():
    root=tk.Tk()
    root.tk.call("tk","scaling",1.5)
    app=DesktopApp(root)
    root.update_idletasks()
    height=min(700,max(620,root.winfo_screenheight()-160))
    root.geometry(f"430x{height}+{max(0,root.winfo_screenwidth()-465)}+35")
    root.after(150,lambda:app.transcript.yview_moveto(0))
    root.mainloop()


if __name__=="__main__":
    main()
