# 知网学术大讲堂 · 网课挂机助手（Online Courses Helper）

## 这项目是什么

一个 **Windows 桌面小工具**，帮助你无人值守地观看**知网学术大讲堂**在线课程的 1 倍速回放，
并自动在后台保持"页面在前台"以让计时持续，再以设备无关的 GitHub 工程形态保存与测试。

**它是什么：**
- 这是一个基于 **Playwright + Tkinter** 的 Windows 桌面自动化工具。
- 无人值守观看：自动登录、逐门打开课程、真实 1 倍速播放、断点续学（以服务端进度为准）。
- 以**服务端 `/kedu/course/list`** 的 `progress / learnState / learnDuration / finishDate` 作为进度的唯一依据。

**它不是什么：**
- 不是破解验证码 / 绕过风控的脚本：遇到滑块/验证码需要**你本人手动完成**。
- 不是万能"刷课"器：只针对知网这个专题、只做真实播放，不做快进/倍速/拖动。
- 不是安全的凭据管理方案：**不建议**长期在磁盘明文保存账号密码（见下）。

## 技术栈

- Python 3.9+（Windows 优先，语义上可在 3.9–3.12 运行；CI 已用 3.9–3.12 matrix 验证）。
- Playwright（Chromium）——浏览器自动化。
- Tkinter —— 桌面 GUI。
- unittest —— 纯逻辑单元测试（无需浏览器）。

## 架构

```
GUI (刷网课.py: Tkinter)
   │  状态/日志/按钮（开始/暂停/继续/停止），每 800ms 刷新
   ▼
Runner (刷网课.py: worker -> run_browser)
   │  阶段切换：补学未完成课程 → 循环补学 → 达到目标时长停止
   │
   ├── cnki_client.py     平台 API：课程列表、学习进度查询、认证头捕获（数据标准化，可 fake page 测试）
   └── browser_session.py Playwright 生命周期、storage_state、headed/headless 切换、登录态判定
          │
          ▼
       Playwright (Chromium)
```

## 目录结构

```
online-courses-helper/
├─ 刷网课.py              # 入口 + GUI + 运行主流程（Worker/Runner）
├─ core.py                # 纯逻辑：URL/凭据/进度解析、完成/目标判定、时长加权总进度、路径 & 登录态文本（可单测）
├─ cnki_client.py         # 知网平台 API：课程列表、学习进度查询、认证头捕获（接收 page，可注入 fake page 测试）
├─ browser_session.py     # Playwright 会话：storage_state 读写、headed 人工登录、headless 加载、登录态判定
├─ tests/
│  └─ test_units.py       # 单元测试（纯 Python，无需浏览器/Chromium）
├─ demo.ipynb             # Jupyter 展示（演示原理与运行示例，账号为占位号）
├─ 账号密码.example.md    # 账号密码占位模板（可选，复制为 账号密码.md 后填写）
├─ requirements.txt       # 运行依赖：playwright>=1.40,<2
├─ .github/workflows/tests.yml   # GitHub Actions CI（matrix 3.9–3.12，编译 + import + 单测）
├─ LICENSE                # MIT
├─ README.md
└─ .gitignore             # 排除 账号密码 / 登录态(session/) / output / chrome_profile 等
```

## 安装

需要 Python 3.9+。

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 安装 Playwright 的 Chromium 浏览器
playwright install chromium

# 3)（可选）准备账号密码，用于自动填写登录表单
copy 账号密码.example.md 账号密码.md   # 然后编辑 账号密码.md
# 不创建 账号密码.md 也可以：程序会弹出可见浏览器让你手动登录。

# 4) 运行
python 刷网课.py
```

> Windows 双击可建一个 `.bat`：
> `start "" "pythonw.exe" 刷网课.py`（把 `pythonw.exe` 换成你的解释器路径）。

## 登录流程

登录状态保存在 **Playwright storage_state**（`session/storage_state.json`），按下面优先级处理：

| 情况 | 行为 |
|---|---|
| 已有有效 storage_state | 直接以 **headless** 模式复用登录态开始（不强制需要账号密码） |
| 无 storage_state，但有**完整**账号+密码 | 弹出**可见浏览器**，自动填写账号密码并点击登录；若出现滑块/验证码由你手动完成 |
| 无 storage_state，且无完整账号密码 | 仍弹出**可见浏览器**，请在窗口中手动登录（不会拒绝运行） |

- 登录成功后，当前会话的登录态自动保存到 `session/storage_state.json`。
- 打开页面检测：若登录态已失效，会自动切回 headed 登录流程并重新保存。

> **"完整账号密码"** 指账号与密码都有；**只填账号或只填密码**都会被当作"无完整凭据"，走手动登录。

## 账号密码的安全性（重要）

- **推荐**：首选"人工登录 + storage_state"，这样无需在磁盘留下明文密码。
- 明文账号密码**只是可选便利项**，用于自动填写登录表单；第一次登录后可删除 `账号密码.md`，只保留 `session/storage_state.json`。
- `账号密码.md`、`session/`（含 `storage_state.json`）、`output/`、`chrome_profile/`、`*.log` 都已加入 `.gitignore`，绝不会被提交到 Git。
- 请不要在共享电脑上长期明文保存密码；不要把这个文件发给别人。

## 运行行为

- 自动获取课程列表（以 **课程 ID** 作为唯一标识，课程名只用于展示；同名课程不会串进度）。
- Phase 1：补学未完成到 100% 的课程。
- Phase 2：全部学完后进入**循环补学**，轮换观看回放，每 120 秒上报一次学习中心累计时长（`较上次 +N 秒`）。
- **达到证书目标时长（默认 15 小时）后自动停止补学**，GUI 显示"已达到目标学习时长"（以服务端累计时长为准，避免目标附近反复启停）。
- "暂停"会真正暂停播放器，且暂停时间不计入"每节课 600 秒"的循环观看额度。
- 运行状态与日志自动落盘到 `output/<run_id>_progress.json` 与 `output/<run_id>_log.txt`。
- 重新启动后会读取服务端已有学习进度，继续未完成课程。

## 常见错误与处理

| 现象 | 原因 / 处理 |
|---|---|
| 弹出可见浏览器要求登录但一直不成功 | 检查账号密码；滑块/验证码需你本人手动完成 |
| 日志提示"未捕获到认证信息…若连续 3 次同步失败，本轮任务将停止" | 暂时无法同步服务端进度；请重新运行触发登录，避免长期空转 |
| 日志提示"连续 3 次无法获取服务端学习进度…已停止" | 登录态/token 失效，请重新运行以触发 headed 登录 |
| 运行时报 `playwright install chromium` | 需先安装 Chromium 与依赖 |
| 某课程显示"打开失败" | 该课程回放可能不可用，脚本会跳过继续下一门 |

## 测试（无需浏览器）

```bash
python -m unittest discover -s tests -v
```

CI（`.github/workflows/tests.yml`）在 push / pull_request 时，用 Python 3.9–3.12 matrix 执行：依赖安装、`py_compile` 编译检查、`import core/browser_session/cnki_client`、以及上面的纯逻辑单测（不下载 Chromium、不访问知网）。

[![tests](https://github.com/jingxingwang4-droid/online-courses-helper/actions/workflows/tests.yml/badge.svg)](https://github.com/jingxingwang4-droid/online-courses-helper/actions/workflows/tests.yml)

## 已知限制

- 登录态判定是启发式（登录页 URL + 登录表单 + 页面文字），页面改版可能误判，但会保守地回退到人工登录。
- 脚本**不会**自动破解滑块/验证码，**不会**绕过所有平台风控；首登或登录态失效需人工完成。
- 运行中途会话过期只会停止本轮，需重新运行触发登录（不做运行中自动重启浏览器）。
- 平台限制快进/倍速/暂停不计时长，脚本全程 1 倍速真实播放，不加速、不拖动。
- 遇到考试/测验弹窗，脚本不会自动作答，会在日志区提示，需要你手动处理。

## 风险与合规

仅供学习自动化 / Playwright 与浏览器自动化研究。请遵守知网平台规则与课程要求，勿用于违规用途。
请勿提交任何真实账号、密码、cookie、token、storage_state 到 Git。

## License

本项目采用 [MIT License](LICENSE)。
