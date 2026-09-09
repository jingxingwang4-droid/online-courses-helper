# -*- coding: utf-8 -*-
"""浏览器会话 / 登录态管理（基于 Playwright 官方 storage_state）。

职责仅限：storage state 的读写、登录态检测、headed 人工登录流程、无头加载。
“运行”主流程仍在 刷网课.py；纯逻辑（路径、JSON 安全解析、登录态文本判定）在 core.py，便于单测。
"""
import os
import time

import core

LOGIN_WAIT_SEC = 300        # 人工登录最多等待时间
CONFIRM_INTERVAL_SEC = 3    # 登录态轮询间隔
VIEWPORT = {"width": 1280, "height": 800}


def storage_path(base_dir):
    return core.storage_state_path(base_dir)


def has_storage_state(base_dir):
    return core.load_json_safe(storage_path(base_dir), None) is not None


def logged_in(page):
    """判断是否已登录。

    提高可靠性：先排除明确的“未登录”信号（登录页 URL / 登录表单可见），
    再回退到页面文字判定。三者都是启发式，失败时保留 headed 人工登录 fallback。
    """
    try:
        if "login.cnki.net" in (page.url or ""):
            return False
        try:
            login_input = page.locator("#TextBoxUserName")
            if login_input.count() > 0 and login_input.first.is_visible():
                return False
        except Exception:
            pass
        body = page.inner_text("body")
        return core.is_logged_in_by_body(body)
    except Exception:
        return False


def save_storage_state(page, base_dir):
    path = storage_path(base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    page.context.storage_state(path=str(path))
    return path


def load_context_authed(p, flags, init_script, base_dir, theme_url):
    """有有效 storage state 时，用 headless 启动并校验登录态。
    返回 (browser, ctx, page)，均已登录；否则返回 (None, None, None)。
    """
    if not has_storage_state(base_dir):
        return None, None, None
    browser = p.chromium.launch(headless=True, args=flags)
    try:
        ctx = browser.new_context(storage_state=storage_path(base_dir), viewport=VIEWPORT, locale="zh-CN")
        ctx.add_init_script(init_script)
        page = ctx.new_page()
        page.goto(theme_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        if logged_in(page):
            return browser, ctx, page
        browser.close()
        return None, None, None
    except Exception:
        try:
            browser.close()
        except Exception:
            pass
        return None, None, None


def interactive_login(p, flags, init_script, base_dir, user, pwd, theme_url, log):
    """headed 人工登录流程：自动填账密，若出现滑块/验证码允许用户手动完成。
    登录成功后保存 storage state 并返回路径；超时/失败返回 None。
    """
    log("登录态缺失或已失效，启动可见浏览器；请在窗口中完成登录（若出现滑块/验证码请手动操作）...")
    browser = p.chromium.launch(headless=False, args=list(flags) + ["--window-size=1200,860"])
    try:
        ctx = browser.new_context(viewport=VIEWPORT, locale="zh-CN")
        ctx.add_init_script(init_script)
        page = ctx.new_page()
        page.goto(theme_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(2)
        if not logged_in(page):
            try:
                page.get_by_text("登录", exact=False).last.click(timeout=8000)
                time.sleep(2)
            except Exception:
                pass
            if user and pwd:
                try:
                    page.fill("#TextBoxUserName", user)
                    page.fill("#TextBoxPwd", pwd)
                    try:
                        page.locator("#agreement").check()
                    except Exception:
                        pass
                    page.locator("#Button1").click()
                    log("已自动填写账号密码并点击登录；请在窗口中完成剩余验证。")
                except Exception as e:
                    log("自动填写登录失败，请在窗口中手动登录: " + str(e))
            else:
                log("未检测到账号密码，请在窗口中手动输入并完成登录。")
        deadline = time.time() + LOGIN_WAIT_SEC
        while time.time() < deadline:
            if logged_in(page):
                path = save_storage_state(page, base_dir)
                log("登录成功，登录态已保存: " + path)
                return path
            time.sleep(CONFIRM_INTERVAL_SEC)
        log("等待登录超时（%d 秒），请检查账号密码后重新运行。" % int(LOGIN_WAIT_SEC))
        return None
    finally:
        try:
            browser.close()
        except Exception:
            pass


def ensure_authenticated(p, flags, init_script, base_dir, user, pwd, theme_url, log):
    """确保已登录，返回 (browser, ctx, page)（均已登录）；否则 (None, None, None)。

    优先级：已有可用 storage state -> headless；否则 -> headed 人工登录（保存 storage state）后
    以 headless 重新启动，符合“后续默认 headless”。
    """
    browser, ctx, page = load_context_authed(p, flags, init_script, base_dir, theme_url)
    if browser is not None:
        log("已复用已有登录态（headless 模式）。")
        return browser, ctx, page
    path = interactive_login(p, flags, init_script, base_dir, user, pwd, theme_url, log)
    if path is None:
        return None, None, None
    return load_context_authed(p, flags, init_script, base_dir, theme_url)
