"""Native Tk widgets shared by the desktop floating assistant."""
import tkinter as tk
from tkinter import ttk

BG = "#f4f5ef"
PAPER = "#ffffff"
INK = "#243e35"
GREEN = "#176b57"
MUTED = "#748578"
LINE = "#dbe3d7"
FONT = "Microsoft YaHei UI"


def label(parent,text="",size=10,color=INK,bg=None,**kwargs):
    return tk.Label(parent,text=text,font=(FONT,size),fg=color,bg=bg or parent.cget("bg"),**kwargs)


def button(parent,text,command,primary=False,danger=False,**kwargs):
    return tk.Button(parent,text=text,command=command,font=(FONT,9),relief="flat",bd=0,
                     bg=GREEN if primary else "#f0f4eb",fg="white" if primary else "#a3483d" if danger else INK,
                     activebackground="#dce9d5",activeforeground=INK,padx=10,pady=6,cursor="hand2",**kwargs)


def replace_text(widget,value):
    if widget.get("1.0","end-1c")==value:return
    position=widget.yview()[0]
    widget.configure(state="normal");widget.delete("1.0","end");widget.insert("1.0",value);widget.configure(state="disabled")
    widget.yview_moveto(position)


class ScrollPage(tk.Frame):
    def __init__(self,parent):
        super().__init__(parent,bg=BG)
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0)
        scrollbar=ttk.Scrollbar(self,orient="vertical",command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right",fill="y");self.canvas.pack(fill="both",expand=True)
        self.body=tk.Frame(self.canvas,bg=BG)
        self.window=self.canvas.create_window((0,0),window=self.body,anchor="nw")
        self.body.bind("<Configure>",lambda e:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(self.window,width=e.width))


class SettingsDialog:
    def __init__(self,app):
        self.app=app
        self.window=tk.Toplevel(app.root)
        self.window.title("模型设置 · 模电实验 Copilot")
        self.window.configure(bg=BG)
        self.window.transient(app.root)
        self.window.resizable(False,False)
        self.window.protocol("WM_DELETE_WINDOW",self.close)
        body=tk.Frame(self.window,bg=BG,padx=22,pady=16);body.pack(fill="both",expand=True)
        label(body,"连接外部模型",size=15,anchor="w").pack(fill="x")
        label(body,"密钥仅保存在本次进程内存；更换地址会清除旧密钥。",size=9,color=MUTED,wraplength=440,justify="left").pack(anchor="w",pady=(5,12))
        current=app.settings.public()
        self.base=tk.StringVar(self.window,current["base_url"])
        self.model=tk.StringVar(self.window,current["model"])
        self.key=tk.StringVar(self.window,"")
        for text,var in (("API 地址",self.base),("模型名称",self.model),("API Key（已配置，留空保留）" if current["has_key"] else "API Key（本次运行有效）",self.key)):
            label(body,text,size=9,anchor="w").pack(fill="x",pady=(8,3))
            entry=ttk.Entry(body,textvariable=var,width=50,show="●" if var is self.key else "")
            entry.pack(fill="x")
            if var is self.key:self.key_entry=entry
        self.error=tk.StringVar(self.window,"")
        label(body,textvariable=self.error,size=9,color="#a3483d",wraplength=440,justify="left").pack(fill="x",pady=10)
        actions=tk.Frame(body,bg=BG);actions.pack(fill="x",pady=7)
        button(actions,"清除本次密钥",self.clear_key).pack(side="left")
        button(actions,"保存设置",self.save,primary=True).pack(side="right")

    def clear_key(self):
        self.app.settings.update({"clear_key":True});self.key.set("")
        self.error.set("本次密钥已清除");self.app.update_model_label()

    def save(self):
        key=self.key.get();self.key.set("")
        try:
            self.app.settings.update({"base_url":self.base.get(),"model":self.model.get(),"api_key":key})
            self.app.controller.event("settings_updated",key_configured=self.app.settings.public()["has_key"])
            self.app.update_model_label();self.close()
        except ValueError as error:
            self.error.set(str(error))
        finally:
            key=""

    def close(self):
        self.key.set("")
        if self.window.winfo_exists():self.window.destroy()
        if self.app.settings_dialog is self:self.app.settings_dialog=None
