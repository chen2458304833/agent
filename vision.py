# -*- coding: utf-8 -*-
"""
suisui 的视觉能力：看图片 / 看视频
用 Ollama 本地视觉模型（qwen2.5vl），不依赖云 API、不联网。
优化点：
  1. 图片加载异常捕获更细
  2. 视频帧抽取容错（cap 打开失败、帧读取失败）
  3. 长视频自动减少帧数避免超时
  4. 统一的 Ollama 调用异常处理
"""
import os
import io
import json
import base64
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 读取配置
_cfg = {}
try:
    with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
        _cfg = json.load(f)
except Exception:
    pass

OLLAMA_URL = _cfg.get("VISION_BASE_URL", "http://127.0.0.1:11434")
VISION_MODEL = _cfg.get("VISION_MODEL", "qwen2.5vl:7b")
MAX_SIDE = 1280
VIDEO_FRAMES = 6
VIDEO_TIMEOUT = 600  # 视频总超时秒数


def _ollama_chat(messages, model=None):
    """调用 Ollama 视觉模型，带异常处理"""
    try:
        r = requests.post(
            OLLAMA_URL.rstrip("/") + "/api/chat",
            json={"model": model or VISION_MODEL, "messages": messages,
                  "stream": False, "options": {"temperature": 0.2}},
            timeout=300,
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")
    except requests.ConnectionError:
        return "无法连接到本地视觉模型，请确认 Ollama 已启动（%s）。" % OLLAMA_URL
    except requests.Timeout:
        return "视觉模型响应超时，请稍后再试。"
    except Exception as e:
        return "视觉模型调用失败: %s" % e


def _pil_to_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _load_resize(path):
    """读图片并缩到合适尺寸，返回 base64"""
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("缺少 Pillow 库，请运行: pip install pillow")
    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:
        raise RuntimeError("无法打开图片: %s" % e)
    w, h = img.size
    scale = MAX_SIDE / max(w, h)
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return _pil_to_b64(img)


def describe_image(path, question="详细描述这张图片里有什么。"):
    """看一张图片"""
    if not os.path.exists(path):
        return "找不到图片文件：%s" % path
    if not os.path.isfile(path):
        return "路径不是文件：%s" % path
    try:
        b64 = _load_resize(path)
    except Exception as e:
        return str(e)
    msgs = [{"role": "user", "content": question, "images": [b64]}]
    return _ollama_chat(msgs)


def describe_video(path, question="请综合描述这个视频的内容。"):
    """看一个视频：抽取关键帧，逐帧识别后汇总"""
    if not os.path.exists(path):
        return "找不到视频文件：%s" % path
    if not os.path.isfile(path):
        return "路径不是文件：%s" % path
    try:
        import cv2
    except ImportError:
        return "缺少 opencv 库，请运行: pip install opencv-python"

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return "无法打开视频文件（可能格式不支持或文件损坏）：%s" % path

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    duration = (total / fps) if fps else 0

    # 长视频减少帧数，避免超时
    n_frames = VIDEO_FRAMES
    if duration > 300:
        n_frames = 4
    if duration > 600:
        n_frames = 3

    frame_b64s = []
    if total > 0:
        for i in range(n_frames):
            idx = int(total * (i + 1) / (n_frames + 1))
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok and frame is not None:
                ok2, buf = cv2.imencode(".jpg", frame)
                if ok2:
                    frame_b64s.append(base64.b64encode(buf.tobytes()).decode())
    cap.release()

    if not frame_b64s:
        return "无法从视频里读取画面（可能格式不支持）。"

    descs = []
    for i, b64 in enumerate(frame_b64s, 1):
        msgs = [{
            "role": "user",
            "content": "这是视频的第 %d/%d 帧，请用一句话描述画面内容。" % (i, len(frame_b64s)),
            "images": [b64]
        }]
        try:
            d = _ollama_chat(msgs)
            descs.append("第%d帧：%s" % (i, d.strip()))
        except Exception as e:
            descs.append("第%d帧：描述失败(%s)" % (i, e))

    return "视频时长约 %.0f 秒，共抽取 %d 帧：\n%s\n\n（用户问题：%s）" % (
        duration, len(frame_b64s), "\n".join(descs), question)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python vision.py <图片或视频路径>")
    else:
        p = sys.argv[1]
        if p.lower().endswith((".mp4", ".avi", ".mov", ".mkv", ".flv", ".webm")):
            print(describe_video(p))
        else:
            print(describe_image(p))
