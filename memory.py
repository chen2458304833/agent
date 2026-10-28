# -*- coding: utf-8 -*-
"""suisui 的记忆系统：SQLite 持久化 + 事实库 + 自动总结
优化点：
  1. 所有 DB 操作用上下文管理器，异常也能正确关闭连接
  2. 事实存储前规范化空白，去重更可靠
  3. 搜索支持多关键词 AND 匹配
  4. 增加按时间清理旧总结的能力
"""
import os
import sqlite3
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "memory.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, role TEXT, content TEXT);
CREATE TABLE IF NOT EXISTS facts(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, text TEXT, tag TEXT);
CREATE TABLE IF NOT EXISTS summaries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, text TEXT);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS idx_facts_ts ON facts(ts);
"""


def _conn():
    c = sqlite3.connect(DB, timeout=10)
    c.executescript(SCHEMA)
    return c


def _normalize(text):
    """规范化空白，便于去重"""
    return " ".join((text or "").split())


# ---------------- 对话 ----------------
def add_message(role, content):
    with _conn() as c:
        c.execute("INSERT INTO messages(ts, role, content) VALUES(?,?,?)",
                  (time.time(), role, str(content)))
        c.commit()


def recent_messages(n=20):
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return list(reversed(rows))


def message_count():
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def delete_old_messages(keep=10):
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        if total > keep:
            c.execute("DELETE FROM messages WHERE id NOT IN "
                      "(SELECT id FROM messages ORDER BY id DESC LIMIT ?)", (keep,))
            c.commit()


def oldest_messages(n=20):
    with _conn() as c:
        return c.execute(
            "SELECT id, role, content FROM messages ORDER BY id ASC LIMIT ?", (n,)
        ).fetchall()


def delete_messages_by_ids(ids):
    if not ids:
        return
    with _conn() as c:
        c.executemany("DELETE FROM messages WHERE id=?", [(i,) for i in ids])
        c.commit()


# ---------------- 事实 ----------------
def add_fact(text, tag=""):
    text = _normalize(text)
    if not text:
        return False
    with _conn() as c:
        exists = c.execute("SELECT id FROM facts WHERE text=?", (text,)).fetchone()
        if exists:
            return False
        c.execute("INSERT INTO facts(ts, text, tag) VALUES(?,?,?)",
                  (time.time(), text, tag))
        c.commit()
    return True


def search_facts(query="", limit=20):
    query = (query or "").strip()
    with _conn() as c:
        if not query:
            rows = c.execute(
                "SELECT text FROM facts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            # 先整句模糊匹配
            rows = c.execute(
                "SELECT text FROM facts WHERE text LIKE ? ORDER BY id DESC LIMIT ?",
                ("%" + query + "%", limit)
            ).fetchall()
            if len(rows) < limit:
                # 拆成关键词做 AND 匹配
                words = [w for w in query.replace("，", " ").replace(",", " ").split()
                         if len(w) >= 2]
                if words:
                    placeholders = " AND ".join(["text LIKE ?"] * len(words))
                    params = ["%" + w + "%" for w in words] + [limit]
                    extra = c.execute(
                        "SELECT text FROM facts WHERE %s ORDER BY id DESC LIMIT ?"
                        % placeholders, params
                    ).fetchall()
                    rows = rows + extra
    # 去重保序
    seen, out = set(), []
    for (t,) in rows:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def all_facts(limit=50):
    return search_facts("", limit)


# ---------------- 总结 ----------------
def add_summary(text):
    with _conn() as c:
        c.execute("INSERT INTO summaries(ts, text) VALUES(?,?)", (time.time(), text))
        c.commit()


def recent_summaries(n=3):
    with _conn() as c:
        rows = c.execute(
            "SELECT text FROM summaries ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
    return [r[0] for r in reversed(rows)]


def cleanup_old_summaries(keep=10):
    """只保留最近 keep 条总结"""
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
        if total > keep:
            c.execute("DELETE FROM summaries WHERE id NOT IN "
                      "(SELECT id FROM summaries ORDER BY id DESC LIMIT ?)", (keep,))
            c.commit()


# ---------------- 统计 / 清理 ----------------
def stats():
    with _conn() as c:
        m = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        f = c.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        s = c.execute("SELECT COUNT(*) FROM summaries").fetchone()[0]
    return {"messages": m, "facts": f, "summaries": s}


def clear_all():
    with _conn() as c:
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM facts")
        c.execute("DELETE FROM summaries")
        c.commit()


def export_text():
    """导出成人类可读的文本"""
    lines = []
    with _conn() as c:
        fs = c.execute("SELECT text FROM facts ORDER BY id").fetchall()
        if fs:
            lines.append("=== 记住的事 ===")
            lines += ["- " + t for (t,) in fs]
            lines.append("")
        ss = c.execute("SELECT text FROM summaries ORDER BY id").fetchall()
        if ss:
            lines.append("=== 对话总结 ===")
            lines += [s for (s,) in ss]
    return "\n".join(lines)


if __name__ == "__main__":
    print("统计:", stats())
    add_fact("测试事实：用户喜欢蓝色")
    print("事实:", all_facts())
