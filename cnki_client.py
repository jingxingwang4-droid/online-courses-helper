# -*- coding: utf-8 -*-
"""知网课程平台的 API 交互（薄封装）。

只负责“页面请求/解析”，接收 Playwright 的 page 与已读取的认证头，返回结构化数据。
不持有 GUI / 全局状态 / 业务循环，便于用 fake page（dependency injection）做单元测试。
"""
import json
import time

import core

LEARN_CENTER_URL = "https://k.cnki.net/personal/learnCenter/course"
COURSE_LIST_URL = "https://k.cnki.net/kedu/course/list"
THEME_COURSE_URL = "https://k.cnki.net/kedu/theme/course?id={theme_id}"

# 用捕获到的认证头去查询学习进度（POST course/list）
_COURSE_LIST_JS = (
    "async (a)=>{try{const r=await fetch('" + COURSE_LIST_URL + "',"
    "{method:'POST',credentials:'include',"
    "headers:{'Content-Type':'application/json','lid':a.lid,'uid':a.uid,'authtoken':a.authtoken,"
    "'edutoken':a.authtoken,'noticetoken':a.authtoken,'orgtoken':a.authtoken,'classtoken':a.authtoken,"
    "'examtoken':a.authtoken,'x-auth':'true'},"
    "body:JSON.stringify({courseTypeID:null,courseType:null,orderType:1,courseName:'',learnType:null,page:1,rows:100,total:0})});"
    "return await r.text();}catch(e){return '{\"ok\":false}';}}"
)


def capture_auth(page):
    """访问学习中心，监听 /kedu/course/list 请求头，取出 {lid, uid, authtoken}。返回 dict。"""
    auth = {"lid": "", "uid": "", "authtoken": ""}

    def on_req(r):
        if "/kedu/course/list" in r.url:
            h = r.headers
            if h.get("authtoken"):
                auth["authtoken"] = h.get("authtoken")
                auth["uid"] = h.get("uid")
                auth["lid"] = h.get("lid")

    page.on("request", on_req)
    try:
        page.goto(LEARN_CENTER_URL, wait_until="networkidle", timeout=60000)
        time.sleep(5)
    finally:
        page.remove_listener("request", on_req)
    return auth


def fetch_progress(page, auth):
    """按课程 ID 索引返回进度 map（由 core.parse_progress_items 生成，key 为 str(courseId)）。

    返回 dict（可能为空=成功但无数据）；请求/解析失败或缺少 token 返回 None。
    """
    if not auth.get("authtoken"):
        return None
    try:
        txt = page.evaluate(_COURSE_LIST_JS, auth)
        d = json.loads(txt)
        if not d.get("success"):
            return None
        items = ((d.get("data") or {}).get("list")) or []
        return core.parse_progress_items(items)
    except Exception:
        return None


def fetch_theme_courses(page, theme_id):
    """返回 [(course_id, display_name, match_name), ...]。

    display_name = tutorTitle（优先）或 courseName，用于 GUI / 日志。
    match_name   = courseName，用于名称 fallback 兼容匹配（与 progress.courseName 同源）。
    请求/解析失败时抛出异常，由调用方记录日志。
    """
    body = page.evaluate(
        "async (u)=>{const r=await fetch(u,{credentials:'include'});return await r.text();}",
        THEME_COURSE_URL.format(theme_id=theme_id),
    )
    data = json.loads(body)["data"]
    out = []
    for item in data:
        cid = str(item["courseId"])
        display = (item.get("tutorTitle", "") or item.get("courseName", "")).strip()
        match = (item.get("courseName", "") or "").strip()
        out.append((cid, display, match))
    return out
