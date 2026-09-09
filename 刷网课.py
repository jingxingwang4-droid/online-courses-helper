import json
import os
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from playwright.sync_api import sync_playwright

from core import (
    DEFAULT_THEME,
    advance_fail_count,
    field_or_current,
    fmt_hms,
    has_full_creds,
    is_course_complete,
    login_mode,
    overall_progress,
    parse_creds_text,
    parse_theme_url,
    fallback_summary,
    progress_for_course_safe,
    reached_cert_target,
    run_scoped_defaults,
    total_learned,
)
import browser_session
import cnki_client
from browser_session import ensure_authenticated

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_FILE = os.path.join(BASE_DIR, "账号密码.md")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
EXTRA_PLAY_SEC = 60
CERT_HOURS = 15
CERT_TOTAL_SECONDS = CERT_HOURS * 3600
PROGRESS_FAIL_LIMIT = 3  # 连续多少次无法获取服务端进度即视为认证失效并停止本轮

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
    def __init__(self, cid, display_name, match_name, target):
        self.cid = cid
        self.name = display_name               # 展示名（GUI/日志用）
        self.match_name = match_name or ""      # 兼容匹配名（名称 fallback 用，通常为 courseName）
        self.target = target if target is not None else 6300.0
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
            "match_name": self.match_name,
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
        self.cert_reached = False
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
                "cert_reached": self.cert_reached,
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
        browser, ctx, page = ensure_authenticated(p, PLAYER_FLAGS, INIT_SCRIPT, BASE_DIR, user, pwd, theme_url, state.log)
        if browser is None:
            state.log("无法完成登录，已停止。若要登录请检查账号密码或等待可见浏览器窗口完成登录。")
            state.running = False
            return
        state.log("已就绪（headless 后台播放）。获取课程列表...")

        state.log("读取学习中心认证信息...")
        try:
            auth = cnki_client.capture_auth(page)
        except Exception as e:
            state.log("读取学习中心失败，暂时无法获取认证信息：%s；若后续连续 %d 次同步失败，本轮将停止。" % (str(e), PROGRESS_FAIL_LIMIT))
            auth = {"lid": "", "uid": "", "authtoken": ""}
        if not auth.get("authtoken"):
            state.log("未捕获到认证信息，暂时无法同步服务端学习进度；若连续 %d 次同步失败，本轮任务将停止。" % PROGRESS_FAIL_LIMIT)
        else:
            state.log("认证信息读取完成。")

        progress_fail = {"count": 0}

        def fetch_progress():
            """包一层连续失败检测：成功清零，连续 N 次失败即停止本轮并提示重新认证。"""
            res = cnki_client.fetch_progress(page, auth)
            progress_fail["count"], should_stop = advance_fail_count(progress_fail["count"], res is not None, PROGRESS_FAIL_LIMIT)
            if should_stop:
                state.log("连续 %d 次无法获取服务端学习进度，可能登录态或认证 token 已失效；已停止本轮，请重新运行以触发登录流程。" % PROGRESS_FAIL_LIMIT)
                state.stop_requested = True
            return res

        courses_data = []
        try:
            courses_data = cnki_client.fetch_theme_courses(page, theme_id)
        except Exception as e:
            state.log("获取课程列表失败: " + str(e))
            state.running = False
            return

        state.log("共获取 " + str(len(courses_data)) + " 门课程")

        name_count = {}
        for _cid, _display, _match in courses_data:
            name_count[_match] = name_count.get(_match, 0) + 1

        def lookup_progress(prog_map, cid, match_name):
            """先按课程 ID 精确匹配；仅当该 match_name 在专题内唯一时才允许名称兜底。"""
            return progress_for_course_safe(prog_map, cid, match_name, name_count.get(match_name, 0) == 1)

        prog_map = fetch_progress() or {}
        if prog_map:
            state.log("已读取到服务器端学习进度")
            _single, _amb = fallback_summary(prog_map)
            for _n in _single:
                if name_count.get(_n, 0) > 1:
                    state.log("专题中存在多个同名课程“%s”，服务端进度又缺少 courseId，已跳过名称兜底以避免串课。" % _n)
                else:
                    state.log("服务端课程“%s”缺少 courseId，将使用课程名称作为兜底匹配。" % _n)
            for _n in _amb:
                state.log("检测到多个缺少 courseId 的同名课程“%s”，名称兜底存在歧义，已跳过自动关联。" % _n)
        else:
            state.log("暂未读取到服务器进度；若连续同步失败达到阈值，本轮将停止。")

        courses = []
        for cid, display, match in courses_data:
            pm = lookup_progress(prog_map, cid, match)
            target = pm["duration"] if pm.get("duration") is not None else 6300.0
            course = Course(cid, display, match, target)
            if pm:
                pct = pm["progress"] if pm.get("progress") is not None else 0.0
                course.percent = float(pct)
                course.watched = target * pct / 100.0
                ls = pm["learnDuration"] if pm.get("learnDuration") is not None else target * pct / 100.0
                course.learn_sec = float(ls)
                course.server_watched = course.learn_sec
                course.already_done = is_course_complete(pm)
            courses.append(course)

        with state.lock:
            state.courses = courses

        if not courses:
            state.log("专题下未获取到可学习课程，已停止。")
            with state.lock:
                state.done = True
                state.running = False
            state.write_output()
            try:
                browser.close()
            except Exception:
                pass
            return

        def refresh_total():
            with state.lock:
                state.total_sec = total_learned(c.learn_sec for c in state.courses)
            return state.total_sec

        def sync_from_server(course):
            """把服务端最新进度回写到 course，并刷新累计时长。注意 0 是合法值，不会回退旧值。"""
            try:
                pm = lookup_progress(fetch_progress() or {}, course.cid, course.match_name)
            except Exception:
                pm = {}
            if not pm:
                return pm
            with state.lock:
                course.learn_sec = field_or_current(pm, "learnDuration", course.learn_sec, float)
                course.percent = field_or_current(pm, "progress", course.percent, float)
                course.server_watched = course.learn_sec
                course.watched = course.target * course.percent / 100.0
                course.server_complete = is_course_complete(pm)
            return pm

        def pause_video():
            try:
                page.evaluate("()=>{document.querySelectorAll('video').forEach(v=>{try{v.pause();}catch(e){}});}")
            except Exception:
                pass

        target_reached = {"v": False}

        def maybe_stop_at_target():
            """服务端累计学习时长达到目标即停止（含滞留判断，避免目标附近反复启停）。"""
            if target_reached["v"]:
                return True
            with state.lock:
                reached = reached_cert_target(state.total_sec, CERT_TOTAL_SECONDS)
            if reached:
                target_reached["v"] = True
                with state.lock:
                    state.cert_reached = True
                    state.done = True
                    state.stop_requested = True
                state.log("累计学习时长已达 %s，达到证书目标，已停止补学。" % fmt_hms(CERT_TOTAL_SECONDS))
                state.write_output()
                return True
            return False

        refresh_total()
        state.log("累计学习时长: %s / %s（证书要求）" % (fmt_hms(state.total_sec), fmt_hms(CERT_TOTAL_SECONDS)))
        state.write_output()
        maybe_stop_at_target()



        if not state.stop_requested:
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
                state.log("会话已过期（已跳转到登录页）。停止本轮；请重新运行以触发 headed 登录流程。")
                state.stop_requested = True
                return False
            return True

        # Phase 1: finish any course not yet 100%
        for idx, course in enumerate(courses):
            if state.stop_requested:
                break
            try:
                pm = lookup_progress(fetch_progress() or {}, course.cid, course.match_name)
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
                    if maybe_stop_at_target():
                        break
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
        if not state.stop_requested:
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
            last_tick = time.time()
            active_accum = 0.0
            while not state.stop_requested and active_accum < WATCH_EACH:
                if state.paused:
                    pause_video()
                    time.sleep(1)
                    last_tick = time.time()
                    continue
                now = time.time()
                active_accum += (now - last_tick)
                last_tick = now
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
                    maybe_stop_at_target()
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
    has_creds = has_full_creds(user, pwd)
    mode = login_mode(browser_session.has_storage_state(BASE_DIR), has_creds)
    if mode == "resume":
        state.log("检测到已有登录态文件（session/storage_state.json），将优先尝试以 headless 复用；若失效会自动触发登录。")
    elif mode == "auto_fill":
        state.log("检测到完整账号密码，将用于自动填写登录；若登录态失效会弹出可见浏览器供你完成验证。")
    else:
        state.log("未检测到完整账号密码且无可用登录态：将弹出可见浏览器，请在窗口中手动完成登录。")
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
            for _k, _v in run_scoped_defaults().items():
                setattr(state, _k, _v)
            state.running = True
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
        state.log("正在停止，等待后台浏览器线程退出...")

        def _poll():
            t = state.thread
            if t is None or not t.is_alive():
                rt.destroy()
                return
            if time.time() - _poll.started > 15:
                rt.destroy()
                return
            rt.after(150, _poll)

        _poll.started = time.time()
        _poll()

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
        remain_total = 0
        for c in snap["courses"]:
            if c["status"] == "已完成":
                remain = 0
            else:
                remain = max(0, int(c["target"] - max(c["watched"], c["server_watched"])))
            remain_total += remain
            table.insert("", "end", values=(c["name"], round(c["target"] / 60), round(c["watched"] / 60), round(remain / 60), f"{c['percent']:.1f}%", c["status"]))
        overall = overall_progress(snap["courses"])
        bar["value"] = overall
        cert_line = "    累计学习: %s / %s" % (fmt_secs(snap["total_sec"]), fmt_secs(snap["cert_total_sec"]))
        if snap["running"] and not snap["done"] and remain_total:
            eta = time.strftime("%H:%M", time.localtime(time.time() + remain_total))
            overall_lbl.config(text="总进度: %.1f%%    预计剩余: %s    预计完成: %s%s" % (overall, fmt_secs(remain_total), eta, cert_line))
        else:
            overall_lbl.config(text="总进度: %.1f%%%s" % (overall, cert_line))
        if snap["paused"]:
            state_lbl.config(text="状态: 已暂停", foreground="#e67e22")
        elif snap["cert_reached"]:
            state_lbl.config(text="状态: 已达到目标学习时长", foreground="#2ecc71")
        elif snap["done"]:
            state_lbl.config(text="状态: 已停止", foreground="#e67e22")
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
