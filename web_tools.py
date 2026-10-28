# -*- coding: utf-8 -*-
"""联网工具：必应搜索 + 网页正文提取（国内可用，无需 API Key）
优化点：
  1. 请求带重试 + 指数退避
  2. 统一超时与异常处理
  3. 编码兜底更稳健
  4. 搜索结果解析容错
"""
import re
import time
import requests
from bs4 import BeautifulSoup

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

TIMEOUT = 15
MAX_RETRIES = 2


def _request_with_retry(method, url, **kwargs):
    """带重试和退避的请求"""
    kwargs.setdefault("headers", UA)
    kwargs.setdefault("timeout", TIMEOUT)
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.request(method, url, **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(0.8 * (attempt + 1))
    raise last_err


def search_bing(query: str, n: int = 5) -> str:
    """用必应搜索，返回格式化的文字结果"""
    try:
        r = _request_with_retry(
            "GET", "https://cn.bing.com/search",
            params={"q": query, "setlang": "zh-CN", "count": n},
        )
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select("li.b_algo")
        if not items:
            # 兜底：尝试其他选择器
            items = soup.select("li.b_algoSlug") or soup.select(".b_caption")
        if not items:
            return "没搜到结果。"
        out = []
        for i, it in enumerate(items[:n], 1):
            a = it.select_one("h2 a")
            if not a:
                continue
            title = a.get_text(strip=True)
            url = a.get("href", "")
            cap = it.select_one(".b_caption p") or it.select_one("p")
            snippet = cap.get_text(strip=True) if cap else ""
            out.append("%d. %s\n   链接: %s\n   摘要: %s" % (
                i, title, url, snippet[:220]))
        return "\n\n".join(out) if out else "没搜到结果。"
    except Exception as e:
        return "搜索失败: %s" % e


def fetch_page(url: str, max_chars: int = 2500) -> str:
    """抓取网页并提取正文（去掉脚本/样式/导航）"""
    try:
        r = _request_with_retry("GET", url)
        # 编码兜底
        if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
            r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "noscript", "iframe"]):
            tag.decompose()
        main = (soup.select_one("article") or soup.select_one("main")
                or soup.body or soup)
        text = main.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n...(已截断)"
        return text or "页面没有可读正文。"
    except Exception as e:
        return "抓取失败: %s" % e


if __name__ == "__main__":
    print(search_bing("今天北京天气", 3))
    print("=" * 40)
    print(fetch_page("https://www.deepseek.com/", 600))
