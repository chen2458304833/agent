# -*- coding: utf-8 -*-
"""
suisui Agent —— 双引擎版（云端 DeepSeek / 本地模型 可随时切换）
功能：对话 + 联网搜索 + 看图/看视频 + 记忆 + 自动总结
引擎切换方式：
  1. 命令行:  python agent_demo.py --local   (用本地模型)
              python agent_demo.py --cloud   (用云端 DeepSeek)
              python agent_demo.py --auto    (云端优先，失败自动回退本地)
  2. 对话中:  输入 /local  切本地
              输入 /cloud  切云端
              输入 /engine 查看当前引擎
  3. config.json 的 USE_LOCAL 仍可作为默认值
"""
import os
import sys
import json
import time
import ast
import operator
import argparse
import threading
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing import Annotated, TypedDict

# ---------------- 配置 ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_config():
    cfg = {}
    p = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            print("读取 config.json 失败:", e)
    return cfg


# ---------------- 引擎管理器 ----------------
class EngineManager:
    """管理云端/本地两个引擎，支持运行时切换 + 自动回退"""

    def __init__(self, cfg, initial="cloud", auto_fallback=False):
        self.cfg = cfg
        self.current = initial          # "cloud" or "local"
        self.auto_fallback = auto_fallback
        self._lock = threading.Lock()
        self.llm = None
        self.llm_with_tools = None
        self._build()

    def _get_llm_params(self, engine):
        if engine == "local":
            return {
                "model": self.cfg.get("LOCAL_MODEL", "qwen2.5:7b"),
                "base_url": self.cfg.get("LOCAL_BASE_URL", "http://127.0.0.1:11434/v1"),
                "api_key": self.cfg.get("LOCAL_API_KEY", "ollama"),
            }
        return {
            "model": self.cfg.get("MODEL", "deepseek-chat"),
            "base_url": self.cfg.get("BASE_URL", "https://api.deepseek.com/v1"),
            "api_key": os.environ.get("DEEPSEEK_API_KEY", "")
                       or self.cfg.get("DEEPSEEK_API_KEY", ""),
        }

    def _build(self):
        p = self._get_llm_params(self.current)
        self.llm = ChatOpenAI(
            model=p["model"],
            api_key=p["api_key"],
            base_url=p["base_url"],
            temperature=0.3,
            timeout=120,
            max_retries=2,
        )
        # 工具绑定（TOOLS 定义在下方，这里延后绑定）
        self.llm_with_tools = None

    def bind_tools(self, tools):
        with self._lock:
            self.llm_with_tools = self.llm.bind_tools(tools)

    def switch(self, engine):
        """切换引擎，返回新引擎名称"""
        engine = engine.lower().strip()
        if engine not in ("cloud", "local"):
            return self.current
        with self._lock:
            if self.current != engine:
                self.current = engine
                self._build()
                # 重新绑定工具（TOOLS 此时已存在）
                try:
                    self.llm_with_tools = self.llm.bind_tools(TOOLS)
                except Exception:
                    pass
        return self.current

    def get_llm_with_tools(self):
        with self._lock:
            return self.llm_with_tools

    @property
    def name(self):
        p = self._get_llm_params(self.current)
        return "%s(%s)" % ("本地" if self.current == "local" else "云端", p["model"])

    @property
    def engine(self):
        return self.current


# 解析命令行参数（仅在直接运行时生效，被 import 时忽略）
def _parse_cli_args():
    if len(sys.argv) <= 1:
        return None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--local", action="store_true", help="使用本地模型")
    parser.add_argument("--cloud", action="store_true", help="使用云端 DeepSeek")
    parser.add_argument("--auto", action="store_true", help="云端优先，失败自动回退本地")
    try:
        args, _ = parser.parse_known_args()
        return args
    except Exception:
        return None


_cli = _parse_cli_args() if __name__ == "__main__" else None

_cfg = load_config()

# 决定初始引擎
if _cli and _cli.local:
    _initial = "local"
elif _cli and _cli.cloud:
    _initial = "cloud"
elif _cli and _cli.auto:
    _initial = "cloud"
    _auto_fallback = True
else:
    _initial = "local" if _cfg.get("USE_LOCAL", False) else "cloud"
    _auto_fallback = bool(_cfg.get("AUTO_FALLBACK", False))

_auto_fallback = _auto_fallback if _cli and _cli.auto else bool(_cfg.get("AUTO_FALLBACK", False))

engine_mgr = EngineManager(_cfg, initial=_initial, auto_fallback=_auto_fallback)

# 云端模式下检查 API Key
if engine_mgr.engine == "cloud" and not _cfg.get("DEEPSEEK_API_KEY", "") \
        and not os.environ.get("DEEPSEEK_API_KEY", ""):
    print("=" * 50)
    print("没找到 DeepSeek API Key！")
    print("  方法1: 在 config.json 里填 DEEPSEEK_API_KEY")
    print("  方法2: 设置环境变量 DEEPSEEK_API_KEY")
    print("  方法3: 运行 python agent_demo.py --local  用本地模型")
    print("  方法4: 运行 python agent_demo.py --auto   云端失败自动回退本地")
    print("=" * 50)
    if sys.stdin and sys.stdin.isatty():
        try:
            input("按回车退出...")
        except Exception:
            pass
    sys.exit(1)

# 工具调用上限
MAX_TOOL_ITERATIONS = 12


# ---------------- 安全计算 ----------------
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("只允许数字")
    if isinstance(node, ast.BinOp):
        op = _ALLOWED_OPS.get(type(node.op))
        if not op:
            raise ValueError("不支持的运算符")
        return op(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _ALLOWED_OPS.get(type(node.op))
        if not op:
            raise ValueError("不支持的一元运算符")
        return op(_safe_eval(node.operand))
    raise ValueError("表达式不合法")


def safe_calculate(expression: str) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        return str(_safe_eval(tree))
    except Exception as e:
        return "计算失败: %s" % e


# ---------------- 工具 ----------------
@tool
def get_time() -> str:
    """获取当前日期和时间"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S 星期%w")


@tool
def calculate(expression: str) -> str:
    """计算数学表达式，例如 '2*3+5'。只支持数字和 + - * / // % ** 运算。"""
    return safe_calculate(expression)


@tool
def web_search(query: str) -> str:
    """联网搜索。当需要查实时信息、新闻、天气、价格、百科等你不确定的内容时使用。"""
    try:
        from web_tools import search_bing
        return search_bing(query, 5)
    except Exception as e:
        return "搜索失败: %s" % e


@tool
def open_url(url: str) -> str:
    """打开一个网页并读取正文。适合在搜索结果里挑一个链接深入看内容。"""
    try:
        from web_tools import fetch_page
        return fetch_page(url, 2500)
    except Exception as e:
        return "抓取失败: %s" % e


@tool
def look_at_image(path: str, question: str = "详细描述这张图片里有什么。") -> str:
    """看一张图片。当用户让你看图片/照片/截图，或给出图片文件路径时使用。path 是图片的完整路径。"""
    try:
        from vision import describe_image
        return describe_image(path, question)
    except Exception as e:
        return "看图失败: %s" % e


@tool
def look_at_video(path: str, question: str = "请综合描述这个视频的内容。") -> str:
    """看一个视频。当用户让你看视频，或给出视频文件路径时使用。path 是视频的完整路径。"""
    try:
        from vision import describe_video
        return describe_video(path, question)
    except Exception as e:
        return "看视频失败: %s" % e


TOOLS = [get_time, calculate, web_search, open_url, look_at_image, look_at_video]
TOOL_MAP = {t.name: t for t in TOOLS}

# ---------------- 记忆 ----------------
import memory as mem


@tool
def remember(text: str) -> str:
    """记住一件重要的事。当用户告诉你他的信息、偏好、约定、或说"记住"时使用。"""
    ok = mem.add_fact(text)
    return "已记住：%s" % text if ok else "这条之前已经记过了"


@tool
def recall(query: str = "") -> str:
    """回忆之前记住的事。query 留空则列出全部记忆。"""
    fs = mem.search_facts(query) if query else mem.all_facts(20)
    if not fs:
        return "没有相关的记忆。"
    return "\n".join("- " + f for f in fs)


TOOLS = TOOLS + [remember, recall]
TOOL_MAP = {t.name: t for t in TOOLS}

# 引擎绑定工具
engine_mgr.bind_tools(TOOLS)


# ---------------- 系统提示缓存 ----------------
_sys_prompt_cache = {"text": None, "fact_count": -1, "summary_count": -1}


def build_system_prompt():
    try:
        st = mem.stats()
        fc, sc = st["facts"], st["summaries"]
        if _sys_prompt_cache["text"] is not None and \
           _sys_prompt_cache["fact_count"] == fc and \
           _sys_prompt_cache["summary_count"] == sc:
            return _sys_prompt_cache["text"]
    except Exception:
        pass

    parts = [
        "你叫suisui。别人问你是谁，你就说你是suisui。回答简洁自然，需要工具时就调用工具。"
        "你有视觉能力：当用户让你看图片/照片/截图或看视频，或者给出了图片/视频文件路径时，"
        "就调用 look_at_image（看图）或 look_at_video（看视频）工具。"
        "注意：每次回复最多调用必要的工具，不要重复调用同一个工具。"
    ]
    try:
        facts = mem.all_facts(30)
        if facts:
            parts.append("【你记得的事】\n" + "\n".join("- " + f for f in facts))
        sums = mem.recent_summaries(2)
        if sums:
            parts.append("【以前聊过的摘要】\n" + "\n".join(sums))
    except Exception:
        pass
    text = "\n\n".join(parts)
    _sys_prompt_cache["text"] = text
    try:
        st = mem.stats()
        _sys_prompt_cache["fact_count"] = st["facts"]
        _sys_prompt_cache["summary_count"] = st["summaries"]
    except Exception:
        pass
    return text


def invalidate_system_prompt_cache():
    _sys_prompt_cache["text"] = None


# ---------------- 状态 ----------------
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# ---------------- 节点 ----------------
def call_model(state: AgentState):
    msgs = [SystemMessage(content=build_system_prompt())] + state["messages"]
    llm_with_tools = engine_mgr.get_llm_with_tools()
    try:
        resp = llm_with_tools.invoke(msgs)
        return {"messages": [resp]}
    except Exception as e:
        # 自动回退：云端失败时尝试本地
        if engine_mgr.auto_fallback and engine_mgr.engine == "cloud":
            print("[自动回退] 云端调用失败，尝试本地模型...")
            engine_mgr.switch("local")
            llm_with_tools = engine_mgr.get_llm_with_tools()
            try:
                resp = llm_with_tools.invoke(msgs)
                return {"messages": [resp]}
            except Exception as e2:
                return {"messages": [ToolMessage(
                    content="模型调用失败（云端和本地均不可用）：%s" % e2,
                    tool_call_id="error")]}
        return {"messages": [ToolMessage(
            content="模型调用失败：%s" % e, tool_call_id="error")]}


def call_tools(state: AgentState):
    last = state["messages"][-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    out = []
    for tc in tool_calls:
        fn = TOOL_MAP.get(tc["name"])
        if not fn:
            out.append(ToolMessage(content="未知工具: %s" % tc.get("name"),
                                   tool_call_id=tc["id"]))
            continue
        try:
            result = fn.invoke(tc["args"])
        except Exception as e:
            result = "工具执行出错: %s" % e
        out.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return {"messages": out}


def should_continue(state: AgentState):
    last = state["messages"][-1]
    tool_rounds = sum(1 for m in state["messages"] if getattr(m, "tool_calls", None))
    if tool_rounds >= MAX_TOOL_ITERATIONS:
        return END
    if getattr(last, "tool_calls", None):
        return "tools"
    return END


# ---------------- 图 ----------------
graph = StateGraph(AgentState)
graph.add_node("agent", call_model)
graph.add_node("tools", call_tools)
graph.set_entry_point("agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")
app = graph.compile()


# ---------------- 对话历史 ----------------
def load_history(max_msgs=20):
    rows = mem.recent_messages(max_msgs)
    msgs = []
    for role, content in rows:
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            from langchain_core.messages import AIMessage
            msgs.append(AIMessage(content=content))
    return msgs


def maybe_summarize(threshold=30, batch=20):
    try:
        if mem.message_count() < threshold:
            return None
        rows = mem.oldest_messages(batch)
        if not rows:
            return None
        text = "\n".join("%s: %s" % (r, c) for _, r, c in rows)
        summary = engine_mgr.llm.invoke([
            SystemMessage(content="把下面这段对话压缩成要点，保留关键信息、约定和用户偏好。用中文，200字以内。"),
            HumanMessage(content=text[:6000]),
        ]).content
        mem.add_summary(summary)
        mem.delete_messages_by_ids([i for i, _, _ in rows])
        invalidate_system_prompt_cache()
        return summary
    except Exception as e:
        print("[总结失败]", e)
        return None


# ---------------- 对话命令处理 ----------------
def handle_command(text):
    """处理 /local /cloud /engine 等命令，返回 (回复, 是否拦截)"""
    cmd = text.strip().lower()
    if cmd in ("/local", "/本地"):
        engine_mgr.switch("local")
        return ("[已切换到本地引擎: %s]" % engine_mgr.name, True)
    if cmd in ("/cloud", "/云端"):
        # 检查 API Key
        if not _cfg.get("DEEPSEEK_API_KEY", "") and not os.environ.get("DEEPSEEK_API_KEY", ""):
            return ("[切换失败] 没有 DeepSeek API Key，无法使用云端。", True)
        engine_mgr.switch("cloud")
        return ("[已切换到云端引擎: %s]" % engine_mgr.name, True)
    if cmd in ("/engine", "/引擎"):
        return ("[当前引擎: %s]" % engine_mgr.name, True)
    if cmd in ("/help", "/帮助"):
        return ("[命令]\n  /local  切本地模型\n  /cloud  切云端 DeepSeek\n  /engine  查看当前引擎\n  /help   显示帮助", True)
    return (None, False)


def chat(user_text):
    """统一入口
    返回 (回复文本, 用到的工具列表, 耗时秒)"""
    # 先处理命令
    reply, intercepted = handle_command(user_text)
    if intercepted:
        return reply, [], 0.0

    t0 = time.time()
    mem.add_message("user", user_text)
    invalidate_system_prompt_cache()

    history = load_history(20)
    result = None
    try:
        result = app.invoke({"messages": history})
        reply = result["messages"][-1].content or ""
    except Exception as e:
        reply = "抱歉，处理你的消息时出错了：%s" % e

    mem.add_message("assistant", reply)

    tools_used = []
    if result:
        for m in result.get("messages", []):
            tcs = getattr(m, "tool_calls", None)
            if tcs:
                tools_used.extend(str(tc.get("name") or "tool") for tc in tcs)

    maybe_summarize()
    return reply, tools_used, time.time() - t0


# ---------------- 交互 ----------------
def main():
    st = mem.stats()
    print("=" * 55)
    print(" suisui（输入 q 退出）  引擎: %s" % engine_mgr.name)
    print(" 记忆: %d 对话 / %d 事实 / %d 总结" % (st["messages"], st["facts"], st["summaries"]))
    print(" 命令: /local 切本地 | /cloud 切云端 | /engine 查看 | /help 帮助")
    print("=" * 55)
    while True:
        try:
            text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text or text.lower() in ("q", "quit", "exit"):
            break
        reply, tools_used, cost = chat(text)
        print("suisui> %s" % reply)
        if tools_used:
            print("   [工具: %s  耗时 %.1fs]" % (", ".join(tools_used), cost))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        import traceback
        print("\n" + "=" * 50)
        print("出错了:", type(e).__name__, e)
        print("=" * 50)
        traceback.print_exc()
    finally:
        if sys.stdin and sys.stdin.isatty():
            try:
                input("\n按回车键退出...")
            except Exception:
                pass
