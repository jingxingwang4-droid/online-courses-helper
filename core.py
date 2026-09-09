# -*- coding: utf-8 -*-
"""纯逻辑工具，不含 Playwright / tkinter，便于单测与复用。"""
import json
import os
import re

DEFAULT_THEME = "https://k.cnki.net/themeInfo/2046"

# 登录态存储目录与文件名（敏感本地文件，已被 .gitignore 忽略）
SESSION_DIR = "session"
STORAGE_STATE_FILE = "storage_state.json"
DEFAULT_DURATION = 6300.0  # 服务端缺失时长时的兜底（秒）


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


def _num(value, cast, default):
    """严格取值：None -> default；0 是合法值，保留；解析失败 -> default。"""
    if value is None:
        return default
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def field_or_current(entry, key, current, cast):
    """合并服务端字段：key 缺失或为 None 时保留 current，否则用 cast 后的服务端值。
    “0”是合法值，不会被当作缺失。"""
    v = entry.get(key) if isinstance(entry, dict) else None
    if v is None:
        return current
    try:
        return cast(v)
    except (TypeError, ValueError):
        return current


def parse_progress_items(items):
    """把服务端 /kedu/course/list 的 list 映射为 {课程名: {...}}。

    progress / learnDuration 的 0 被保留为合法值；仅 None 才回退默认。
    """
    out = {}
    for it in items or []:
        name = (it.get("courseName") or "").strip()
        if not name:
            continue
        out[name] = {
            "progress": _num(it.get("progress"), float, 0.0),
            "learnState": it.get("learnState"),
            "duration": _num(it.get("duration"), float, DEFAULT_DURATION),
            "learnDuration": _num(it.get("learnDuration"), int, 0),
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


def load_json_safe(path, default=None):
    """安全读取 JSON：文件缺失 / JSON 损坏 / 读取出错一律返回 default。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def storage_state_path(base_dir):
    """返回 Playwright storage_state 的落盘路径。"""
    return os.path.join(base_dir, SESSION_DIR, STORAGE_STATE_FILE)


def is_logged_in_by_body(body):
    """粗略的登录态文本判定（沿用原逻辑：出现“学习中心”且无“登录注册”）。"""
    body = body or ""
    return ("学习中心" in body) and ("登录注册" not in body)


def has_full_creds(user, pwd):
    """只有同时提供账号与密码才算“完整凭据”；缺任一项视为不完整。"""
    return bool(user) and bool(pwd)


def login_mode(has_storage, has_creds):
    """根据是否存在有效登录态与是否提供账号密码，决定登录策略。

    返回：
      "resume"    有有效 storage_state -> 直接 headless 复用（账号密码非必需）
      "auto_fill" 无 storage_state 但有账号密码 -> headed 自动填写登录
      "manual"    无 storage_state 且无账号密码 -> headed 手动登录（仍允许继续，不拒绝运行）
    """
    if has_storage:
        return "resume"
    return "auto_fill" if has_creds else "manual"


def advance_fail_count(count, ok, limit):
    """连续失败计数：成功(ok=True)清零；失败累加。返回 (新计数, 是否达到阈值停止)。"""
    if ok:
        return 0, False
    new = count + 1
    return new, (new >= limit)
