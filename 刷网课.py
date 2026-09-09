import json
import os
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from playwright.sync_api import sync_playwright

from core import (
    DEFAULT_THEME,
    fmt_hms,
    is_course_complete,
    parse_creds_text,
    parse_progress_items,
    parse_theme_url,
    total_learned,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(BASE_DIR, "账号密码.md")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
EXTRA_PLAY_SEC = 60
CERT_HOURS = 15
CERT_TOTAL_SECONDS = CERT_HOURS * 3600

INIT_SCRIPT = r"""
(() => {
  const vis = () => 'visible';
  try { Object.defineProperty(document, 'visibilityState', { get: vis, configurable: true }); } catch (e) {}
  try { Object.defineProperty(document, 'webkitVisibilityState', { get: vis, configurable: true }); } catch (e) {}
  for (const k of ['hidden', 'webkitHidden', 'mozHidden', 'msHidden']) {
    try { Object.defineProperty(document, k, { get: () => false, configurable: true }); } catch (e) {}
  }
  try { Object.defineProperty(document, 'hasFocus', { value: () => true, configurable: true }); } catch (e) {}
  try { Object.defineProperty(window, 'onblur', { value: null, configurable: true }); } catch (e) {}
})();
"""

PLAYER_FLAGS = [
    "--mute-audio",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=CalculateNativeWinOcclusion",
    "--no-default-browser-check",
    "--disable-popup-blocking",
]


def read_creds():
    try:
        with open(CRED_FILE, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    return parse_creds_text(text)


class Course:
    def __init__(self, cid, name, target):
        self.cid = cid
        self.name = name
        self.target = target or 6300.0
        self.watched = 0.0
        self.server_watched = 0.0
        self.server_complete = False
        self.already_done = False
        self.learn_sec = 0.0
        self.status = "等待"
        self.error = ""
        self.percent = 0.0

    def to_dict(self):
        return {
            "cid": self.cid,
            "name": self.name,
            "target": self.target,
            "watched": self.watched,
            "server_watched": self.server_watched,
            "learn_sec": self.learn_sec,
            "status": self.status,
            "error": self.error,
            "percent": self.percent,
        }


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.courses = []
        self.log_lines = []
        self.running = False
        self.paused = False
        self.stop_requested = False
        self.done = False
        self.account = ""
        self.pwd_input = ""
        self.theme_url = DEFAULT_THEME
        self.theme_id = "2046"
        self.run_id = time.strftime("%Y%m%d_%H%M%S")
        self.current_cid = None
        self.start_time = None
        self.total_sec = 0.0
        self.cert_total_sec = CERT_TOTAL_SECONDS
        self.thread = None

    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        with self.lock:
            self.log_lines.append(f"[{ts}] {msg}")
            if len(self.log_lines) > 2000:
                self.log_lines = self.log_lines[-2000:]

    def snapshot(self):
        with self.lock:
            return {
                "courses": [c.to_dict() for c in self.courses],
                "log": list(self.log_lines),
                "running": self.running,
                "paused": self.paused,
                "done": self.done,
                "account": self.account,
                "theme_url": self.theme_url,
                "current_cid": self.current_cid,
                "run_id": self.run_id,
                "start_time": self.start_time,
                "total_sec": self.total_sec,
                "cert_total_sec": self.cert_total_sec,
            }

    def write_output(self):
        snap = self.snapshot()
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            prog = {
                "theme_url": snap["theme_url"],
                "account": snap["account"],
                "start_time": snap["start_time"],
                "done": snap["done"],
                "total_sec": snap["total_sec"],
                "cert_total_sec": snap["cert_total_sec"],
                "courses": snap["courses"],
            }
            with open(os.path.join(OUTPUT_DIR, f"{snap['run_id']}_progress.json"), "w", encoding="utf-8") as f:
                json.dump(prog, f, ensure_ascii=False, indent=2)
            with open(os.path.join(OUTPUT_DIR, f"{snap['run_id']}_log.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(snap["log"]))
        except OSError:
            pass


state = State()


def run_browser(user, pwd, theme_url):
    with state.lock:
        state.account = user
        state.theme_url = theme_url
        state.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
    state.log("读取账号完成: " + user)
    state.log("课程专题: " + theme_url)

    theme_url, theme_id = parse_theme_url(theme_url)
    with state.lock:
        state.theme_id = theme_id

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=PLAYER_FLAGS)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="zh-CN")
        ctx.add_init_script(INIT_SCRIPT)
        page = ctx.new_page()
        state.log("已启动隐藏浏览器，开始登录...")

        def login():
            page.goto(theme_url, wait_until="networkidle", timeout=60000)
            time.sleep(2)
            body = page.inner_text("body")
            if "学习中心" in body and "登录注册" not in body:
                return True
            with page.expect_navigation(timeout=15000):
                page.get_by_text("登录", exact=False).last.click()
            time.sleep(3)
            page.fill("#TextBoxUserName", user)
            page.fill("#TextBoxPwd", pwd)
            try:
                page.locator("#agreement").check()
            except Exception:
                pass
            time.sleep(0.5)
            page.locator("#Button1").click()
            time.sleep(6)
            return "login.cnki.net" not in page.url

        if not login():
            state.log("登录失败，请检查账号密码")
            state.running = False
            return

        state.log("登录成功，获取课程列表...")

        auth = {"lid": "", "uid": "", "authtoken": ""}

        def refresh_auth():
            def on_req(r):
                if "/kedu/course/list" in r.url:
                    h = r.headers
                    if h.get("authtoken"):
                        auth["authtoken"] = h.get("authtoken")
                        auth["uid"] = h.get("uid")
                        auth["lid"] = h.get("lid")
            page.on("request", on_req)
            try:
                page.goto("https://k.cnki.net/personal/learnCenter/course", wait_until="networkidle", timeout=60000)
                time.sleep(5)
            except Exception:
                pass
            page.remove_listener("request", on_req)

        state.log("读取学习中心进度...")
        refresh_auth()

        def get_progress():
            if not auth.get("authtoken"):
                return {}
            js = ("async (a)=>{try{const r=await fetch('https://k.cnki.net/kedu/course/list',"
                  "{method:'POST',credentials:'include',"
                  "headers:{'Content-Type':'application/json','lid':a.lid,'uid':a.uid,'authtoken':a.authtoken,"
                  "'edutoken':a.authtoken,'noticetoken':a.authtoken,'orgtoken':a.authtoken,'classtoken':a.authtoken,"
                  "'examtoken':a.authtoken,'x-auth':'true'},"
                  "body:JSON.stringify({courseTypeID:null,courseType:null,orderType:1,courseName:'',learnType:null,page:1,rows:100,total:0})});"
                  "return await r.text();}catch(e){return '{\"ok\":false}';}}")
            try:
                txt = page.evaluate(js, auth)
                d = json.loads(txt)
                if not d.get("success"):
                    return {}
                items = ((d.get("data") or {}).get("list")) or []
                return parse_progress_items(items)
            except Exception:
                return {}

        course_ids = []
        course_names = []
        try:
            body = page.evaluate(
                "async (u)=>{const r=await fetch(u,{credentials:'include'});return await r.text();}",
                f"https://k.cnki.net/kedu/theme/course?id={theme_id}",
            )
            data = json.loads(body)["data"]
            for item in data:
                course_ids.append(str(item["courseId"]))
                course_names.append(item.get("tutorTitle", "") or item.get("courseName", ""))
        except Exception as e:
            state.log("获取课程列表失败: " + str(e))
            state.running = False
            return

        state.log("共获取 " + str(len(course_ids)) + " 门课程")

        prog_map = get_progress()
        if prog_map:
            state.log("已读取到服务器端学习进度")
        else:
            state.log("未能读取服务器进度，将按视频时长继续")

        courses = []
        for cid, name in zip(course_ids, course_names):
            pm = prog_map.get(name) or {}
            target = pm.get("duration") or 6300.0
            course = Course(cid, name, target)
            if pm:
                pct = pm.get("progress") or 0.0
                course.percent = float(pct)
                course.watched = target * pct / 100.0
                course.learn_sec = float(pm.get("learnDuration") or target * pct / 100.0)
                course.server_watched = course.learn_sec
                course.already_done = is_course_complete(pm)
            courses.append(course)

        with state.lock:
            state.courses = courses

        def refresh_total():
            with state.lock:
                state.total_sec = total_learned(c.learn_sec for c in state.courses)
            return state.total_sec

        def sync_from_server(course):
            """把服务端最新进度回写到 course，并刷新累计时长。"""
            try:
                pm = get_progress().get(course.name) or {}
            except Exception:
                pm = {}
            if not pm:
                return pm
            with state.lock:
                course.learn_sec = float(pm.get("learnDuration") or course.learn_sec)
                course.percent = float(pm.get("progress") or course.percent)
                course.server_watched = course.learn_sec
                course.watched = course.target * course.percent / 100.0
                course.server_complete = is_course_complete(pm)
            return pm

        def pause_video():
            try:
                page.evaluate("()=>{document.querySelectorAll('video').forEach(v=>{try{v.pause();}catch(e){}});}")
            except Exception:
                pass

        refresh_total()
        state.log("累计学习时长: %s / %s（证书要求）" % (fmt_hms(state.total_sec), fmt_hms(CERT_TOTAL_SECONDS)))
        state.write_output()



        state.log("学习开始：先补学未完成课程，然后循环观看回放并观察学习时长增长")

        def mute_and_play_from_start():
            page.evaluate("()=>{document.querySelectorAll('video').forEach(v=>{v.muted=true;v.volume=0;});}")
            page.evaluate("()=>{const v=document.querySelector('video'); if(v){v.muted=true;v.volume=0; v.currentTime=0; v.play().catch(()=>{});} }")

        def read_video():
            try:
                return page.evaluate("()=>{const v=document.querySelector('video'); if(!v) return null; return {t:v.currentTime, dur:v.duration, paused:v.paused, muted:v.muted, ended:v.ended};}")
            except Exception:
                return None

        def keep_alive(last):
            info = read_video()
            if info:
                if not info["muted"]:
                    page.evaluate("()=>{document.querySelectorAll('video').forEach(v=>{v.muted=true;v.volume=0;});}")
                if info["paused"] and time.time() - last[0] > 4:
                    page.evaluate("()=>{const v=document.querySelector('video'); if(v){v.muted=true;v.volume=0; v.play().catch(()=>{});} }")
                    last[0] = time.time()
                if info.get("dur") and (info.get("ended") or info["t"] >= info["dur"] - 8):
                    page.evaluate("()=>{const v=document.querySelector('video'); if(v){v.currentTime=0; v.play().catch(()=>{});} }")
                    last[0] = time.time()
            return info

        def open_course(course):
            page.goto("https://k.cnki.net/courseLearn/" + course.cid, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("video", timeout=60000)
            time.sleep(3)
            mute_and_play_from_start()
            time.sleep(2)

        def relogin_if_needed(course):
            if "login.cnki.net" in page.url:
                state.log("会话已过期，重新登录后继续...")
                if login():
                    refresh_auth()
                    try:
                        open_course(course)
                        return True
                    except Exception:
                        return False
            return True

        # Phase 1: finish any course not yet 100%
        for idx, course in enumerate(courses):
            if state.stop_requested:
                break
            try:
                pm = get_progress().get(course.name) or {}
            except Exception:
                pm = {}
            if (pm.get("learnState") == 2 or (pm.get("progress") or 0) >= 100 or pm.get("finishDate") or course.already_done):
                continue
            with state.lock:
                course.status = "学习中"
            state.log("补学未完成课程: " + course.name)
            try:
                open_course(course)
            except Exception as e:
                state.log("打开失败: " + course.name + " -> " + str(e))
                continue
            last = [time.time()]
            last_check = 0.0
            while not state.stop_requested:
                if state.paused:
                    pause_video()
                    time.sleep(1)
                    continue
                if not relogin_if_needed(course):
                    break
                keep_alive(last)
                if time.time() - last_check > 45:
                    last_check = time.time()
                    pm = sync_from_server(course)
                    refresh_total()
                    if is_course_complete(pm):
                        with state.lock:
                            course.status = "已完成"
                            course.percent = 100.0
                            course.watched = course.target
                        state.log("服务器确认学完: " + course.name)
                        state.write_output()
                        break
                time.sleep(5)

        # Phase 2: endless top-up — rotate watching replays, report learning-center total growth
        WATCH_EACH = 600
        LOG_EVERY = 120
        pidx = 0
        last_log = time.time()
        last_total = refresh_total()
        state.log("进入循环补学：轮换观看回放，每 %d 秒报告学习中心累计时长" % LOG_EVERY)
        while not state.stop_requested:
            if state.paused:
                time.sleep(2)
                continue
            course = courses[pidx % len(courses)]
            pidx += 1
            state.current_cid = course.cid
            with state.lock:
                course.status = "学习中"
            state.log("循环观看: " + course.name)
            try:
                open_course(course)
            except Exception as e:
                state.log("打开失败: " + course.name + " -> " + str(e))
                time.sleep(3)
                continue
            last = [time.time()]
            seg_start = time.time()
            while not state.stop_requested and (time.time() - seg_start < WATCH_EACH):
                if state.paused:
                    pause_video()
                    time.sleep(2)
                    continue
                if not relogin_if_needed(course):
                    break
                keep_alive(last)
                if time.time() - last_log > LOG_EVERY:
                    last_log = time.time()
                    sync_from_server(course)
                    new_total = refresh_total()
                    state.log("累计学习时长: %s / %s　(较上次 %+d 秒)" % (fmt_hms(new_total), fmt_hms(CERT_TOTAL_SECONDS), int(new_total - last_total)))
                    last_total = new_total
                    state.write_output()
                time.sleep(5)

        with state.lock:
            state.done = True
            state.running = False
        state.log("已停止，当前累计学习时长: %s" % fmt_hms(refresh_total()))
        state.write_output()
        browser.close()


def worker():
    user, pwd = read_creds()
    with state.lock:
        user = state.account or user
        pwd = state.pwd_input or pwd
        theme_url = state.theme_url
    if not user or not pwd:
        state.log("请填写账号密码")
        return
    try:
        run_browser(user, pwd, theme_url)
    except Exception as e:
        state.log("运行出错: " + str(e))
    finally:
        with state.lock:
            state.running = False


def build_gui():
    root = tk.Tk()
    root.title("知网网课自动完成助手")
    root.geometry("1000x760")
    root.protocol("WM_DELETE_WINDOW", lambda: shutdown(root))

    cred_user, cred_pwd = read_creds()

    cfg = ttk.LabelFrame(root, text="配置（通用版）", padding=8)
    cfg.pack(fill="x", padx=10, pady=(8, 4))
    ttk.Label(cfg, text="账号:").grid(row=0, column=0, sticky="e", padx=4, pady=2)
    user_var = tk.StringVar(value=cred_user)
    ttk.Entry(cfg, textvariable=user_var, width=30).grid(row=0, column=1, sticky="w", padx=4, pady=2)
    ttk.Label(cfg, text="密码:").grid(row=0, column=2, sticky="e", padx=4, pady=2)
    pwd_var = tk.StringVar(value=cred_pwd)
    ttk.Entry(cfg, textvariable=pwd_var, show="*", width=30).grid(row=0, column=3, sticky="w", padx=4, pady=2)
    ttk.Label(cfg, text="课程专题链接/ID:").grid(row=1, column=0, sticky="e", padx=4, pady=2)
    theme_var = tk.StringVar(value=DEFAULT_THEME)
    ttk.Entry(cfg, textvariable=theme_var, width=70).grid(row=1, column=1, columnspan=3, sticky="w", padx=4, pady=2)
    ttk.Label(cfg, text="原理: 后台隐藏播放+伪装前台，仅按真实时长计时（平台限1倍速、禁快进）", foreground="#888",
              font=("", 9)).grid(row=2, column=0, columnspan=4, sticky="w", padx=4, pady=(2, 0))

    top = ttk.Frame(root, padding=6)
    top.pack(fill="x")
    state_lbl = ttk.Label(top, text="状态: 空闲", foreground="#999")
    state_lbl.pack(side="right")

    bar = ttk.Progressbar(root, maximum=100, mode="determinate")
    bar.pack(fill="x", padx=10, pady=(0, 4))
    overall_lbl = ttk.Label(root, text="总进度: 0%")
    overall_lbl.pack(anchor="w", padx=12)

    table = ttk.Treeview(root, columns=("name", "target", "watched", "remain", "percent", "status"), show="headings", height=6)
    for col, title, w in (("name", "课程", 400), ("target", "需学(分)", 82), ("watched", "已学(分)", 82), ("remain", "剩余(分)", 82), ("percent", "进度", 84), ("status", "状态", 110)):
        table.heading(col, text=title)
        table.column(col, anchor="center" if col != "name" else "w", width=w)
    table.pack(fill="x", padx=10, pady=6)

    btns = ttk.Frame(root, padding=6)
    btns.pack(fill="x")
    start_btn = ttk.Button(btns, text="开始学习", command=lambda: start(user_var, pwd_var, theme_var))
    start_btn.pack(side="left", padx=4)
    pause_btn = ttk.Button(btns, text="暂停", command=lambda: pause_resume())
    pause_btn.pack(side="left", padx=4)
    stop_btn = ttk.Button(btns, text="停止", command=lambda: stop())
    stop_btn.pack(side="left", padx=4)
    ttk.Label(btns, text="运行结果自动保存到 output 文件夹", foreground="#666", font=("", 9)).pack(side="right")

    log_box = scrolledtext.ScrolledText(root, height=14, state="disabled", font=("Consolas", 9))
    log_box.pack(fill="both", expand=True, padx=10, pady=(6, 10))

    def start(uv, pv, tv):
        if state.running:
            return
        prev = state.thread
        if prev is not None and prev.is_alive():
            state.log("上一个任务仍在收尾（即将退出），请稍候片刻再开始...")
            return
        with state.lock:
            state.account = uv.get().strip()
            state.pwd_input = pv.get()
            state.theme_url = parse_theme_url(tv.get().strip())[0]
            state.run_id = time.strftime("%Y%m%d_%H%M%S")
            state.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
            state.running = True
            state.stop_requested = False
            state.paused = False
            state.done = False
            state.thread = threading.Thread(target=worker, daemon=True)
        state.log("已开始，正在启动后台浏览器线程...")
        state.thread.start()

    def pause_resume():
        with state.lock:
            state.paused = not state.paused
        state.log("已暂停" if state.paused else "已继续")

    def stop():
        with state.lock:
            state.stop_requested = True
        state.log("已请求停止")

    def shutdown(rt):
        with state.lock:
            state.stop_requested = True
        rt.destroy()

    def fmt_secs(sec):
        sec = max(0, int(sec))
        h, r = divmod(sec, 3600)
        m, s = divmod(r, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

    last_write = [0.0]

    def refresh():
        snap = state.snapshot()
        for row in table.get_children():
            table.delete(row)
        total = 0.0
        remain_total = 0
        for c in snap["courses"]:
            total += c["percent"]
            if c["status"] == "已完成":
                remain = 0
            else:
                remain = max(0, int(c["target"] - max(c["watched"], c["server_watched"])))
            remain_total += remain
            table.insert("", "end", values=(c["name"], round(c["target"] / 60), round(c["watched"] / 60), round(remain / 60), f"{c['percent']:.1f}%", c["status"]))
        cnt = len(snap["courses"])
        overall = (total / cnt) if cnt else 0.0
        bar["value"] = overall
        cert_line = "    累计学习: %s / %s" % (fmt_secs(snap["total_sec"]), fmt_secs(snap["cert_total_sec"]))
        if snap["running"] and not snap["done"] and remain_total:
            eta = time.strftime("%H:%M", time.localtime(time.time() + remain_total))
            overall_lbl.config(text="总进度: %.1f%%    预计剩余: %s    预计完成: %s%s" % (overall, fmt_secs(remain_total), eta, cert_line))
        else:
            overall_lbl.config(text="总进度: %.1f%%%s" % (overall, cert_line))
        if snap["paused"]:
            state_lbl.config(text="状态: 已暂停", foreground="#e67e22")
        elif snap["done"]:
            state_lbl.config(text="状态: 完成", foreground="#2ecc71")
        elif snap["running"]:
            state_lbl.config(text="状态: 运行中 (账号 " + snap["account"] + ")", foreground="#2980b9")
        else:
            state_lbl.config(text="状态: 空闲", foreground="#999")
        log_box.config(state="normal")
        log_box.delete("1.0", "end")
        log_box.insert("1.0", "\n".join(snap["log"][-500:]))
        log_box.config(state="disabled")
        log_box.see("end")
        if snap["running"] and time.time() - last_write[0] > 5:
            state.write_output()
            last_write[0] = time.time()
        root.after(800, refresh)

    refresh()
    root.mainloop()


if __name__ == "__main__":
    build_gui()
