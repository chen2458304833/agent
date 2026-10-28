# -*- coding: utf-8 -*-
"""
suisui Web 服务 —— 让别人用浏览器访问你的 agent
启动: python server.py [端口]
访问: http://<你的IP>:8000
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

# 可选访问口令：在 config.json 里加 "WEB_TOKEN": "xxx"
_cfg = {}
_cfg_path = os.path.join(BASE_DIR, "config.json")
if os.path.exists(_cfg_path):
    try:
        with open(_cfg_path, encoding="utf-8") as f:
            _cfg = json.load(f)
    except Exception:
        pass
TOKEN = _cfg.get("WEB_TOKEN", "")

_lock = threading.Lock()

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>suisui</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#1e1e28;color:#e6e6e6;font-family:"Microsoft YaHei",system-ui,sans-serif;height:100vh;display:flex;flex-direction:column}
header{background:#2a2a3a;padding:14px 18px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
h1{font-size:18px;color:#8fd3ff}
#status{font-size:12px;color:#7ee787}
#chat{flex:1;overflow-y:auto;padding:18px;font-size:15px;line-height:1.7}
.msg{margin-bottom:14px;white-space:pre-wrap;word-break:break-word}
.user{color:#8fd3ff;font-weight:bold}
.ai{color:#e6e6e6}
.tool{color:#c8a2ff;font-size:12px}
.sys{color:#7ee787;font-size:13px}
footer{padding:12px;background:#1e1e28;display:flex;gap:8px;flex-shrink:0}
#inp{flex:1;background:#2a2a3a;border:none;color:#fff;font-size:15px;padding:12px;border-radius:6px;outline:none;font-family:inherit}
#btn{background:#3b6ef5;color:#fff;border:none;padding:12px 24px;border-radius:6px;font-size:15px;cursor:pointer;font-family:inherit}
#btn:disabled{background:#444;cursor:not-allowed}
</style>
</head>
<body>
<header><h1>suisui</h1><button id="engbtn" style="background:#3a3a52;color:#8fd3ff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;font-family:inherit">引擎: 加载中…</button><span id="status">就绪</span></header>
<div id="chat"></div>
<footer>
<input id="inp" placeholder="说点什么…（试试：今天北京天气）" autocomplete="off">
<button id="btn">发送</button>
</footer>
<script>
const chat=document.getElementById('chat'),inp=document.getElementById('inp'),btn=document.getElementById('btn'),st=document.getElementById('status');
const engbtn=document.getElementById('engbtn');
let curEngine='cloud';
async function refreshEngine(){
  try{const r=await fetch('engine');const d=await r.json();if(d.ok){curEngine=d.engine;engbtn.textContent='引擎: '+(d.engine==='local'?'本地':'云端');}}
  catch(e){}
}
engbtn.onclick=async()=>{
  const target=curEngine==='local'?'cloud':'local';
  try{const r=await fetch('engine',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({engine:target,token:'__TOKEN__'})});
    const d=await r.json();if(d.ok){curEngine=d.engine;engbtn.textContent='引擎: '+(d.engine==='local'?'本地':'云端');add('[已切换到 '+engbtn.textContent+']','sys');}}
  catch(e){add('[切换失败] '+e,'sys');}
};
refreshEngine();
function add(text,cls){const d=document.createElement('div');d.className='msg '+cls;d.textContent=text;chat.appendChild(d);chat.scrollTop=chat.scrollHeight;}
add('你好，我是suisui。试试问我：\n· 今天北京天气怎么样\n· 看看 D:/dpsk/_vision_test.png 里有什么\n· 记住我叫往尘','sys');
async function send(){
  const q=inp.value.trim(); if(!q) return;
  inp.value=''; add('你 > '+q,'user'); btn.disabled=true; st.textContent='思考中…'; st.style.color='#ffd166';
  try{
    const r=await fetch('chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:q,token:'__TOKEN__'})});
    const d=await r.json();
    if(d.error){add('[错误] '+d.error,'sys');}
    else{
      add('suisui > '+d.reply,'ai');
      if(d.tools&&d.tools.length) add('   [工具: '+d.tools.join(', ')+'  '+d.cost+'s]','tool');
    }
  }catch(e){add('[网络错误] '+e,'sys');}
  btn.disabled=false; st.textContent='就绪'; st.style.color='#7ee787'; inp.focus();
}
btn.onclick=send;
inp.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
inp.focus();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._send(200, HTML.replace("__TOKEN__", TOKEN), "text/html; charset=utf-8")
        elif p == "/status":
            try:
                import memory as mem
                import agent_demo
                self._send(200, json.dumps({
                    "ok": True,
                    "memory": mem.stats(),
                    "engine": agent_demo.engine_mgr.name,
                }, ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        elif p == "/engine":
            try:
                import agent_demo
                self._send(200, json.dumps({
                    "ok": True,
                    "engine": agent_demo.engine_mgr.engine,
                    "name": agent_demo.engine_mgr.name,
                }, ensure_ascii=False))
            except Exception as e:
                self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path
        if p not in ("/chat", "/engine"):
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as e:
            self._send(400, json.dumps({"error": "bad json: %s" % e}, ensure_ascii=False))
            return

        if TOKEN and body.get("token") != TOKEN:
            self._send(403, json.dumps({"error": "需要访问口令"}, ensure_ascii=False))
            return

        # 引擎切换接口
        if p == "/engine":
            try:
                import agent_demo
                target = (body.get("engine") or "").lower().strip()
                if target in ("cloud", "local"):
                    agent_demo.engine_mgr.switch(target)
                self._send(200, json.dumps({
                    "ok": True,
                    "engine": agent_demo.engine_mgr.engine,
                    "name": agent_demo.engine_mgr.name,
                }, ensure_ascii=False))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))
            return

        msg = (body.get("message") or "").strip()
        if not msg:
            self._send(400, json.dumps({"error": "消息为空"}, ensure_ascii=False))
            return

        try:
            with _lock:                      # 串行处理，避免记忆库并发写
                import agent_demo
                reply, tools, cost = agent_demo.chat(msg)
            self._send(200, json.dumps({
                "reply": reply or "",
                "tools": tools,
                "cost": round(cost, 1),
            }, ensure_ascii=False))
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False))


def main():
    import socket
    try:
        host_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        host_ip = "127.0.0.1"
    print("=" * 55)
    print(" suisui Web 服务已启动")
    print(" 本机访问:  http://127.0.0.1:%d" % PORT)
    print(" 局域网访问: http://%s:%d" % (host_ip, PORT))
    print(" 访问口令:  %s" % (TOKEN if TOKEN else "无（任何人都能连）"))
    print(" 按 Ctrl+C 停止")
    print("=" * 55)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
