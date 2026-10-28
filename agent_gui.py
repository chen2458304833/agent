# -*- coding: utf-8 -*-
"""
suisui —— 图形界面版（高DPI清晰版）
双击 start_gui.bat 启动
"""
import os
import sys
import json
import time
import threading
import ctypes

# ---------- 必须先声明 DPI 感知，再创建窗口 ----------
def _enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # 每显示器 DPI 感知
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# ---------- 读取配置 ----------
_cfg = {}
_cfg_path = os.path.join(BASE_DIR, "config.json")
if os.path.exists(_cfg_path):
    with open(_cfg_path, encoding="utf-8") as f:
        _cfg = json.load(f)

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "") or _cfg.get("DEEPSEEK_API_KEY", "")


class ChatApp:
    def __init__(self, root):
        self.root = root

        # DPI 缩放系数（1920x1080 @125% -> 1.25）
        try:
            dpi = root.winfo_fpixels("1i")
        except Exception:
            dpi = 96.0
        self.S = max(1.0, dpi / 96.0)

        def f(size):
            return int(round(size * self.S))

        def px(v):
            return int(round(v * self.S))

        self.f, self.px = f, px

        root.title("suisui")
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w, h = px(780), px(640)
        x = (sw - w) // 2
        y = (sh - h) // 2 - px(20)
        root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        root.minsize(px(620), px(480))
        root.configure(bg="#1e1e28")

        self.history = []
        self.busy = False

        # ---- 顶部 ----
        header = tk.Frame(root, bg="#2a2a3a", height=px(50))
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="suisui", bg="#2a2a3a", fg="#8fd3ff",
                 font=("Microsoft YaHei", f(14), "bold")).pack(side="left", padx=px(16))
        self.status = tk.Label(header, text="就绪", bg="#2a2a3a", fg="#7ee787",
                               font=("Microsoft YaHei", f(10)))
        self.status.pack(side="right", padx=px(16))
        self.mem_label = tk.Label(header, text="记忆 0 · 事实 0 · 总结 0", bg="#2a2a3a",
                                  fg="#8a8aa0", font=("Microsoft YaHei", f(9)))
        self.mem_label.pack(side="right", padx=px(6))
        self.engine_btn = tk.Button(header, text=self.engine_text(), command=self.toggle_engine,
                                    bg="#3a3a52", fg="#8fd3ff", relief="flat",
                                    font=("Microsoft YaHei", f(9)), padx=px(10), cursor="hand2",
                                    activebackground="#4a4a66", activeforeground="#8fd3ff")
        self.engine_btn.pack(side="left", padx=px(10))
        self.refresh_memory()

        # ---- 输入区（先 pack 到底部，保证永不被挤掉）----
        bottom = tk.Frame(root, bg="#1e1e28", height=px(58))
        bottom.pack(side="bottom", fill="x", padx=px(10), pady=(px(6), px(10)))
        bottom.pack_propagate(False)
        self.entry = tk.Entry(bottom, bg="#2a2a3a", fg="#ffffff",
                              font=("Microsoft YaHei", f(12)), insertbackground="#ffffff",
                              relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=px(8), padx=(0, px(8)))
        self.entry.bind("<Return>", lambda e: self.send())
        self.btn = tk.Button(bottom, text="发送", command=self.send,
                             bg="#3b6ef5", fg="white", font=("Microsoft YaHei", f(11), "bold"),
                             relief="flat", padx=px(22), cursor="hand2",
                             activebackground="#2f5bd0", activeforeground="white")
        self.btn.pack(side="right", fill="y")
        self.img_btn = tk.Button(bottom, text="看图", command=self.pick_image,
                                 bg="#5a5a72", fg="white", font=("Microsoft YaHei", f(10)),
                                 relief="flat", padx=px(12), cursor="hand2",
                                 activebackground="#484860", activeforeground="white")
        self.img_btn.pack(side="right", fill="y", padx=(0, px(6)))
        self.vid_btn = tk.Button(bottom, text="看视频", command=self.pick_video,
                                 bg="#5a5a72", fg="white", font=("Microsoft YaHei", f(10)),
                                 relief="flat", padx=px(12), cursor="hand2",
                                 activebackground="#484860", activeforeground="white")
        self.vid_btn.pack(side="right", fill="y", padx=(0, px(6)))

        # ---- 聊天区 ----
        self.chat = scrolledtext.ScrolledText(
            root, wrap="word", bg="#14141c", fg="#e6e6e6",
            font=("Microsoft YaHei", f(11)), insertbackground="#ffffff",
            relief="flat", padx=px(16), pady=px(14))
        self.chat.pack(side="top", fill="both", expand=True, padx=px(10), pady=(px(10), px(4)))
        self.chat.tag_config("user", foreground="#8fd3ff", font=("Microsoft YaHei", f(11), "bold"))
        self.chat.tag_config("ai", foreground="#e6e6e6", font=("Microsoft YaHei", f(11)))
        self.chat.tag_config("tool", foreground="#c8a2ff", font=("Microsoft YaHei", f(9)))
        self.chat.tag_config("sys", foreground="#7ee787", font=("Microsoft YaHei", f(10)))
        self.chat.insert("end", "你好，我是suisui。试试问我：\n"
                                "  · 今天北京天气怎么样？   （联网搜索）\n"
                                "  · 帮我查一下 2026 诺贝尔物理学奖\n"
                                "  · 现在几点，然后算 88*9\n\n", "sys")
        self.chat.configure(state="disabled")
        self.entry.focus_set()

    def append(self, text, tag):
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def send(self):
        if self.busy:
            return
        q = self.entry.get().strip()
        if not q:
            return
        self.entry.delete(0, "end")
        self.append("你 > ", "user")
        self.append(q + "\n", "ai")
        self.busy = True
        self.status.config(text="思考中...", fg="#ffd166")
        self.btn.config(state="disabled")
        threading.Thread(target=self.worker, args=(q,), daemon=True).start()

    def pick_image(self):
        p = filedialog.askopenfilename(title="选择一张图片", filetypes=[
            ("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("所有文件", "*.*")])
        if not p:
            return
        self.entry.delete(0, "end")
        self.entry.insert(0, "看看这张图片，详细描述一下里面的内容：%s" % p)
        self.send()

    def pick_video(self):
        p = filedialog.askopenfilename(title="选择一个视频", filetypes=[
            ("视频", "*.mp4 *.avi *.mov *.mkv *.flv *.webm"), ("所有文件", "*.*")])
        if not p:
            return
        self.entry.delete(0, "end")
        self.entry.insert(0, "看看这个视频，描述一下里面的内容：%s" % p)
        self.send()

    def worker(self, q):
        from langchain_core.messages import HumanMessage
        try:
            import agent_demo
            reply, tools, cost = agent_demo.chat(q)
            self.root.after(0, self.append, "suisui > ", "ai")
            self.root.after(0, self.append, (reply or "") + "\n", "ai")
            if tools:
                self.root.after(0, self.append,
                                "   [工具: %s  %.1fs]\n" % (", ".join(tools), cost), "tool")
            self.root.after(0, self.append, "\n", "ai")
            self.root.after(0, self.refresh_memory)
        except Exception as e:
            import traceback
            self.root.after(0, self.append, "\n[错误] %s\n" % e, "sys")
            self.root.after(0, self.append, traceback.format_exc()[-500:] + "\n", "sys")
        finally:
            self.busy = False
            self.root.after(0, lambda: self.status.config(text="就绪", fg="#7ee787"))
            self.root.after(0, lambda: self.btn.config(state="normal"))

    def engine_text(self):
        try:
            import agent_demo
            return "引擎: " + agent_demo.engine_mgr.name
        except Exception:
            return "引擎: 未知"

    def toggle_engine(self):
        if self.busy:
            return
        try:
            import agent_demo
            cur = agent_demo.engine_mgr.engine
            target = "local" if cur == "cloud" else "cloud"
            agent_demo.engine_mgr.switch(target)
            self.engine_btn.config(text=self.engine_text())
            self.append("[已切换] %s\n\n" % self.engine_text(), "sys")
        except Exception as e:
            self.append("[切换失败] %s\n" % e, "sys")

    def refresh_memory(self):
        """更新顶部记忆统计"""
        try:
            import memory as mem
            st = mem.stats()
            self.mem_label.config(
                text="记忆 %d · 事实 %d · 总结 %d" % (st["messages"], st["facts"], st["summaries"]))
        except Exception:
            pass


def main():
    # 本地模式不需要 API Key
    use_local = bool(_cfg.get("USE_LOCAL", False))
    if not use_local and not API_KEY:
        import tkinter.messagebox as mb
        mb.showerror("缺少 API Key",
                     "请在 config.json 里填写 DEEPSEEK_API_KEY\n或将 USE_LOCAL 设为 true 使用本地模型")
        return
    root = tk.Tk()
    ChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
