# 知网学术大讲堂 · 网课挂机助手（Online Courses Helper）

一个 Windows 下可无人值守、自动观看**知网学术大讲堂**在线课程回放的小工具。
它使用 Playwright 的无头 Chromium，**1 倍速真实播放**，并通过伪装"页面在前台"绕过站点的前台检测；
以**服务端 `/kedu/course/list`** 的 `progress / learnState / learnDuration / finishDate` 作为进度的唯一依据。
内置 GUI 监控器，实时显示每门课进度、总进度与累计学习时长；运行状态与日志自动落盘，重启后读取服务端已有进度并继续未完成课程。

> ⚠️ 仅供学习自动化 / Playwright 与浏览器自动化研究。请遵守平台规则与课程要求，勿用于违规用途。
> 请复制 `账号密码.example.md` 为 `账号密码.md` 并填写**你自己的**账号密码；请勿提交真实凭据/登录态。

## 功能

- **可靠的登录态持久化**（基于 Playwright 官方 `storage_state`，见"登录流程"）。
- 读取 `账号密码.md` 自动登录；首次或登录态失效时弹出**可见浏览器**供你手动完成滑块/验证码。
- 自动获取课程列表，逐门打开课程回放，**1 倍速真实播放**（平台限制快进/倍速，故不加速、不拖动）。
- 绕过"浏览器必须在台前"的限制：最小化或完全被遮挡也按真实时长计时。
- 以服务端接口判断"已学完/进度"，而非视频 `currentTime`。
- 运行状态与日志自动落盘到 `output/<run_id>_progress.json` 与 `output/<run_id>_log.txt`；重新启动后会读取服务端已有学习进度并继续未完成课程。
- 全部学完后进入**循环补学**，轮换观看回放，每 120 秒上报一次学习中心累计时长（`较上次 +N 秒`）。
- GUI：开始 / 暂停 / 继续 / 停止；"暂停"会真正暂停播放器，且暂停时间不占用"循环补学每节课 600 秒"的观看额度。

## 登录流程（storage_state 持久化）

首次运行或登录态失效时：

1. 启动 **headed（可见）Chromium**。
2. 打开目标页面，尝试自动填写账号密码并点击登录。
3. 若出现**滑块 / 验证码 / 其他人工验证**，请直接在浏览器窗口中手动完成（脚本**不会**自动破解验证码）。
4. 检测到登录成功后，将当前 context 的登录态保存到 `session/storage_state.json`（Playwright 标准 storage_state）。

后续运行：

1. 若 `session/storage_state.json` 存在且有效，直接以 **headless** 模式启动并载入该登录态。
2. 打开页面检测是否仍已登录。
3. 若登录态已失效：关闭 headless 浏览器 → 自动切回 headed 登录流程 → 登录成功后重新保存 storage state → 继续正常运行。

> `session/`（含 `storage_state.json`）是**敏感本地文件**，已加入 `.gitignore`，**不会**提交到 Git。
> 该机制使用 Playwright 官方 storage_state，**不依赖**、也不复用你平时使用的普通 Chrome profile。
> 对 storage state 文件缺失、JSON 损坏、读取失败等情况会安全降级到 headed 登录流程。

## 它如何工作

1. **无头启动 + 防节流参数**（`PLAYER_FLAGS`）：`--mute-audio`、`--disable-background-timer-throttling`、
   `--disable-backgrounding-occluded-windows`、`--disable-renderer-backgrounding`、
   `--disable-features=CalculateNativeWinOcclusion` 等。
2. **注入脚本伪装前台**（`INIT_SCRIPT`）：覆盖/伪造 `document.visibilityState`、`document.hidden`、`document.hasFocus`（页面始终认为在前台且可见），并把 `window.onblur` 置空以屏蔽失焦处理；配合 Chromium 后台节流/遮挡参数。
3. **捕获认证**：访问学习中心时监听 `GET /kedu/course/list` 请求头，取出 `lid / uid / authtoken`。
4. **以服务端为准获取进度**：用捕获的认证头 `POST /kedu/course/list`，解析
   `progress`、`learnState`、`duration`、`learnDuration`、`finishDate`。
5. **严格字段合并**：服务端返回的 `0` 是合法值（不会被当作缺失），仅 `None`/字段缺失才回退旧值。
6. **保活**：周期性把视频 `muted` 并 `play()`；每 45/120 秒把服务端最新进度回写，保证累计时长与 GUI 进度实时同步。

## 工程结构

```
online-courses-helper/
├─ 刷网课.py              # 入口：GUI + 挂机主流程（Playwright worker）
├─ core.py                # 纯逻辑：URL/凭据/进度解析、完成判定、登录态文本判定、storage 路径（可单测）
├─ browser_session.py     # 会话/登录态管理：storage_state 读写、headed 人工登录、无头加载
├─ tests/
│  └─ test_units.py       # 单元测试（纯 Python，无需浏览器/Playwright）
├─ demo.ipynb             # Jupyter 成果展示（演示原理与运行示例，账号已用占位号）
├─ 账号密码.example.md    # 账号密码占位模板（复制为 账号密码.md 后填写）
├─ requirements.txt       # 运行依赖：playwright>=1.40
├─ .github/workflows/tests.yml   # GitHub Actions CI（仅跑纯逻辑测试）
├─ README.md
└─ .gitignore             # 排除 账号密码 / 登录态(session/) / output / chrome_profile 等
```

## 环境与运行

需要 Python 3.9+。

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 安装 Playwright 的 Chromium
playwright install chromium

# 3) 准备账号（Windows）
copy 账号密码.example.md 账号密码.md    # 然后编辑 账号密码.md，填入你自己的账号密码

# 4) 运行
python 刷网课.py
```

> Windows 双击运行可建一个 `.bat`，例如：
> `start "" "pythonw.exe" 刷网课.py`（把 `pythonw.exe` 换成你的解释器路径即可）。

## 测试（无需浏览器）

单元测试仅依赖标准库，不安装 Chromium、不访问知网：

```bash
python -m unittest discover -s tests -v
```

仓库已配置 GitHub Actions（`.github/workflows/tests.yml`），在 `push` / `pull_request` 时自动用 Python 3.11 运行上述纯逻辑测试：

[![tests](https://github.com/jingxingwang4-droid/online-courses-helper/actions/workflows/tests.yml/badge.svg)](https://github.com/jingxingwang4-droid/online-courses-helper/actions/workflows/tests.yml)

## 说明与限制

- 站点规定快进 / 倍速 / 暂停不计时长，故脚本全程 **1 倍速真实播放**，不加速、不拖动。
- 脚本**不会**自动破解滑块/验证码，**不会**绕过所有平台风控；首登或登录态失效时需你本人完成人工验证。
- 六门课总时长约 15+ 小时，建议分几天挂完（进度保留在 `output/<run_id>_progress.json`）。
- 遇到考试 / 测验弹窗，脚本不会乱点，会在日志区提示，需要你手动处理。
- `session/`、`output/`、`账号密码.md`、`chrome_profile/` 均为敏感/生成内容，已从版本控制中排除。

## 文件说明

| 文件 | 说明 |
|---|---|
| `刷网课.py` | 主程序（GUI + Playwright 挂机逻辑） |
| `core.py` | 纯逻辑工具（解析、判定、登录态文本判定、storage 路径），可单测 |
| `browser_session.py` | 登录态管理与 headed 人工登录流程 |
| `tests/test_units.py` | 单元测试（`unittest`，纯 Python） |
| `demo.ipynb` | Jupyter 展示文件 |
| `账号密码.example.md` | 账号密码占位模板（复制为 `账号密码.md` 后填写） |
| `requirements.txt` | `playwright>=1.40` |
| `.gitignore` | 排除 账号密码、登录态(session/)、output、chrome_profile 等 |
