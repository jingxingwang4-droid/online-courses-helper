# Online Courses Helper

一个基于 **Python + Playwright + Tkinter** 的 Windows 桌面自动化工具，用于观看**知网学术大讲堂**在线课程回放。

它做的是：用无头 Chromium **真实 1 倍速**播放课程，自动登录（登录态持久化）、以**服务端学习进度**为准、逐门补学、最后轮播回放来累计学习时长，达到设定的累计学习时间后自动结束，并提供一个 Tkinter 监控界面。

它不是：破解验证码、绕过平台风控、快进/倍速/拖动的"挂机神器"。遇到滑块/验证码需要你本人手动完成。

## 功能概览（与当前实现一致）

- Tkinter GUI：开始/暂停/继续/停止，实时显示每门课进度、总进度、累计学习时长、状态。
- Playwright Chromium：无头后台播放；最小化/被遮挡也按真实时长计时。
- **登录态持久化**：首次或登录态失效时弹可见浏览器人工登录，成功后保存 `session/storage_state.json`；后续默认 headless 复用。
- 账号密码**仅作为可选自动填写**；无完整账号密码也可完全手动登录。
- **courseId 优先**关联课程；仅当服务端缺 `courseId` 时才考虑 `courseName` 兜底。
- 名称兜底有**两层保护**：progress 侧同名歧义不匹配；theme 侧同名多门课不允许兜底（避免串课）。
- 课程完成状态与累计学习时长**优先以服务端返回值为准**；本地播放器时间主要用于播放控制、轮播节奏与 GUI 展示；若服务端进度连续获取失败则停止本轮。
- 连续 API 同步失败达到阈值（3 次）即停止本轮并提示重新认证。
- Phase 1：依次处理并补学当前未完成课程；Phase 2：Phase 1 遍历结束后，轮换观看课程回放以补充服务端累计学习时长。
- 默认达到 **15 小时** 累计学习时长自动停止。
- "暂停" 真正暂停播放器，且暂停时间不计入 Phase 2 每节课的轮播观看时长。
- 运行日志与状态落盘到 `output/<run_id>_progress.json` 与 `output/<run_id>_log.txt`。
- GitHub Actions + unittest。

## 工作流程

```
Tkinter GUI
    ↓
run_browser / worker（阶段切换：补未完成课程 → 轮播补时长 → 达标停止）
    ↓
┌──────────────────────────┐
│ browser_session.py       │  登录 / storage_state / headed / headless
└──────────────────────────┘
    ↓
┌──────────────────────────┐
│ cnki_client.py           │  课程 / 进度 / 认证头 API
└──────────────────────────┘
    ↓
core.py                    纯逻辑：数据解析、匹配、进度/目标计算、登录态判定
```

业务流程：
```
读取服务端状态
    ↓
依次处理未完成课程
    ↓
Phase 1 遍历结束
    ↓
轮播回放补累计时长
    ↓
服务端累计 >= 15h
    ↓
正常结束
```

## 课程进度匹配策略

匹配优先级：

1. **`courseId`（第一优先级）**：绝大多数情况按 ID 精确关联。
2. 仅在服务端某条记录缺 `courseId` 时，才考虑用 `courseName` 兜底。

为避免同名课程串课，名称兜底有两条硬性保护：

- **progress 侧**：多条缺 `courseId` 且同名 的记录 → 标记歧义，不进行自动匹配。
- **theme 侧**：专题内多个不同 `courseId` 共用同一个 `match_name` → 禁止名称兜底。

注意区分两个名称字段：

- `display_name`：用于 GUI 与日志展示（theme 取 `tutorTitle` 优先，缺则 `courseName`）。
- `match_name`：用于名称兜底匹配（严格取 `courseName`，与 progress 侧同源）。

`courseId` 精确匹配不受 `display_name` 影响。

## 总进度与证书目标

这是**两个不同概念**，不要混淆：

- **课程完成总进度**：`已学习的课程时长 / 总课程时长`（时长加权），而非简单平均各门课百分比。由 `core.overall_progress` 计算，限制在 0~100%。
- **证书累计学习时间**：服务端 `learnDuration` 汇总。默认 `15 * 3600` 秒，达到后自动停止（`core.reached_cert_target`）。

"某门课完成度 100%" ≠ "累计学习时间达标"。

## 登录机制

| 情况 | 行为 |
|---|---|
| 已有有效 `storage_state` | 直接 headless 复用，无需账号密码 |
| 无有效 storage_state + 有*完整*账号密码 | 弹可见浏览器，自动填写账号密码，滑块/验证码由你手动完成 |
| 无有效 storage_state + 无*完整*账号密码 | 弹可见浏览器，完全手动登录 |

> - `session/storage_state.json` 是**敏感本地文件**，已加入 `.gitignore`，不会提交到 Git。
> - `账号密码.md` 不是必需；推荐首次手动登录后**删除**明文密码文件，只保留 storage_state。
> - "完整账号密码" = 账号与密码都有；缺任一即视为无完整凭据，走手动登录。

## 安装与运行

需要 Python 3.9+（Windows 优先；Python 3.9–3.12 已由 CI 验证）。Tkinter 通常随官方 Windows Python 安装。

```bash
pip install -r requirements.txt
playwright install chromium
python 刷网课.py
```

Windows 双击运行可建一个 `.bat`，如：`start "" "pythonw.exe" 刷网课.py`。

## 项目结构

| 文件 | 职责 |
|---|---|
| `刷网课.py` | 入口 + GUI + 业务流程编排（Worker/Runner） |
| `core.py` | 纯逻辑：解析、匹配、进度/目标计算、登录态判定 |
| `cnki_client.py` | 知网平台 API 薄封装（课程列表 / 进度 / 认证头） |
| `browser_session.py` | Playwright 生命周期、storage_state、headed/headless |
| `tests/` | 纯逻辑单元测试 |
| `demo.ipynb` | Jupyter 演示：核心逻辑与数据匹配（纯逻辑，可 Run All） |
| `账号密码.example.md` | 可选账号密码占位模板（复制为 `账号密码.md` 后填写，非必需） |
| `requirements.txt` | `playwright>=1.40,<2` |
| `README.md` | 本文件 |
| `LICENSE` | MIT |
| `.github/workflows/tests.yml` | CI |

## 测试与 CI

```bash
python -m unittest discover -s tests -v
python -m py_compile core.py browser_session.py cnki_client.py 刷网课.py
```

CI（`.github/workflows/tests.yml`）在 Python **3.9 / 3.10 / 3.11 / 3.12** 上自动执行：

- requirements 安装；
- `py_compile` 编译检查；
- `import core, browser_session, cnki_client`；
- 上面这条 unit test 命令。

CI **不**运行真实 Chromium 登录测试，也**不**访问知网。

[![tests](https://github.com/jingxingwang4-droid/online-courses-helper/actions/workflows/tests.yml/badge.svg)](https://github.com/jingxingwang4-droid/online-courses-helper/actions/workflows/tests.yml)

## 已知限制

- 网站接口 / DOM 改版会导致脚本失效。
- 登录态判定是启发式（登录页 URL + 登录表单 + 页面文字），改版可能误判，但会保守回退到人工登录。
- CAPTCHA / 滑块必须人工完成。
- 运行中登录态失效：当前策略是停止本轮并提示重新运行触发登录，不做运行中自动重启浏览器。
- 名称 fallback 只是**兼容机制**，可靠性低于 `courseId`。
- 关闭 GUI 会尝试等待后台线程清理（轮询 + 15s 超时兜底），Playwright 卡顿时可能只能强退。
- CI 不运行真实浏览器。
- 网络异常会影响服务端进度同步。

## 安全与隐私

- `账号密码.md`、`session/`（含 `storage_state.json`）、`output/`、`chrome_profile/`、`*.log` 均已加入 `.gitignore`，不会提交到 Git。
- 仓库中所有示例均使用明显虚构内容（如 `示例课程A`、`course-001`、`2026-01-01`），不含真实或仿真手机号/密码/token。
- 请勿提交任何真实账号、密码、cookies、token、storage_state。

## License

本项目采用 [MIT License](LICENSE)。
