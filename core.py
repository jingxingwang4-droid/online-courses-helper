# -*- coding: utf-8 -*-
"""纯逻辑工具，不含 Playwright / tkinter，便于单测与复用。"""
import re

DEFAULT_THEME = "https://k.cnki.net/themeInfo/2046"


def fmt_hms(sec):
    sec = max(0, int(sec or 0))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%d:%02d" % (m, s))


def parse_theme_url(raw):
    """从 链接 / 主题ID / 含数字的字符串 里解析出 主题页URL 和 theme_id。"""
    raw = (raw or "").strip()
    m = re.search(r"themeInfo/(\d+)", raw)
    if m:
        tid = m.group(1)
    elif re.fullmatch(r"\d+", raw):
        tid = raw
    else:
        m = re.search(r"(\d+)", raw)
        tid = m.group(1) if m else DEFAULT_THEME.split("/")[-1]
    return "https://k.cnki.net/themeInfo/" + tid, tid


def parse_creds_text(text):
    """从 账号密码.md 文本解析出 (账号, 密码)。找不到返回空串。"""
    um = re.search(r"账号[:：]\s*(\S+)", text or "")
    pm = re.search(r"密码[:：]\s*(\S+)", text or "")
    return (um.group(1).strip() if um else ""), (pm.group(1).strip() if pm else "")


def parse_progress_items(items):
    """把服务端 /kedu/course/list 的 list 映射为 {课程名: {...}}。"""
    out = {}
    for it in items or []:
        name = (it.get("courseName") or "").strip()
        if not name:
            continue
        out[name] = {
            "progress": float(it.get("progress") or 0.0),
            "learnState": it.get("learnState"),
            "duration": float(it.get("duration") or 0) or 6300.0,
            "learnDuration": int(it.get("learnDuration") or 0),
            "finishDate": it.get("finishDate"),
        }
    return out


def is_course_complete(entry):
    """服务端视角判定一门课是否完成。"""
    if not entry:
        return False
    return entry.get("learnState") == 2 or (entry.get("progress") or 0) >= 100 or bool(entry.get("finishDate"))


def total_learned(learn_values):
    """求累计已学秒数。"""
    return float(sum(v or 0.0 for v in learn_values))
