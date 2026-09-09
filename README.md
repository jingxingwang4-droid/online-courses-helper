# 知网学术大讲堂 · 网课挂机助手（Online Courses Helper）

一个 Windows 下可无人值守、自动观看**知网学术大讲堂**在线课程回放的小工具：启动专用**无头 Chromium**、自动登录、逐门打开课程，**1 倍速真实播放**，并通过伪装"页面在前台"绕过站点的前台检测；以**服务端 `/kedu/course/list`** 的 `progress / learnState / learnDuration / finishDate` 作为进度的唯一依据。带 GUI 监控器，实时显示每门课进度、总进度、累计学习时长，进度落盘可断点续学。

> ⚠️ 仅供学习自动化 / Playwright 与浏览器自动化研究。请遵守平台规则与课程要求，勿用于违规用途。
> 请复制 `账号密码.example.md` 为 `账号密码.md` 并填写**你自己的**账号密码；不要提交真实凭据。

## 功能

- 读取 `账号密码.md` 中的账号密码自动登录（`headless=True`，日志区可见进度与心跳）。
- 自动获取课程列表，逐门打开课程回放，**1 倍速真实播放**（平台限制快进/倍速，故不加速、不拖动）。
- 绕过"浏览器必须在台前"的限制：最小化或完全被遮挡也按真实时长计时。
- 以**服务端接口**判断"已学完/进度"，而非视频 `currentTime`。
- 进度自动落盘到 `output/<run_id>_progress.json` 与 `output/<run_id>_log.txt`，中断后可续学。
- 全部学完后进入**循环补学**，轮换观看回放，每 120 秒上报一次学习中心累计时长（`较上次 +N 秒`）。
- GUI：开始 / 暂停 / 继续 / 停止；"暂停"会真正暂停播放器，停止前后切换不会产生两个浏览器实例。

## 它如何工作

1. **无头启动 + 防节流参数**（`PLAYER_FLAGS`）：
   `--mute-audio`、`--disable-background-timer-throttling`、`--disable-backgrounding-occluded-windows`、
   `--disable-renderer-backgrounding`、`--disable-features=CalculateNativeWinOcclusion` 等。
2. **注入脚本伪造前台**（`INIT_SCRIPT`）：覆盖 `document.visibilityState/visibilitychange/hidden/hasFocus`，
   让页面永远认为窗口已获得焦点、且可见。
3. **捕获认证**：监听访问学习中心时机器的 `GET /kedu/course/list` 请求头，取出 `lid / uid / authtoken`。
4. **以服务端为准获取进度**：用捕获到的认证头 `POST /kedu/course/list`，解析
   `progress`（百分比）、`learnState`（2=学完）、`duration`、`learnDuration`（已学秒数）、`finishDate`。
5. **保活**：周期性把视频 `muted` 并 `play()`，避免意外暂停；每 45/120 秒把服务端最新 `learnDuration` 回写，
   从而让"累计学习时长"与 GUI 进度**实时同步**（修复了此前累计恒为 +0 的问题）。

## 工程结构

```
online-courses-helper/
├─ 刷网课.py              # 入口：GUI + 挂机主流程（Playwright worker）
├─ core.py                # 纯逻辑：URL/凭据/进度解析、完成判定、时长格式化（可单测）
├─ tests/
│  └─ test_units.py       # 单元测试（20+ 例，纯 Python，无需浏览器/Playwright）
├─ demo.ipynb             # Jupyter 成果展示（演示原理与运行示例，账号已用占位号）
├─ 账号密码.example.md    # 账号密码占位模板（复制为 账号密码.md 后填写）
├─ requirements.txt       # 运行依赖：playwright>=1.40
├─ README.md
└─ .gitignore             # 排除凭据 / 会话 / 生成产物
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

### 运行单元测试（无需浏览器）

```bash
python -m unittest discover -s tests -v
```

## 说明与限制

- 站点规定快进 / 倍速 / 暂停不计时长，故脚本全程 **1 倍速真实播放**，不加速、不拖动。
- 若站点在校验阶段要求**滑块/验证码**，无头模式无法弹出界面，需先保证账号已在浏览器会话中登录，或按需调整登录逻辑。
- 六门课总时长约 15+ 小时，建议分几天挂完（进度保留在 `output/<run_id>_progress.json`）。
- 遇到考试 / 测验弹窗，脚本不会乱点，会在日志区提示，需要你手动处理。

## 文件说明

| 文件 | 说明 |
|---|---|
| `刷网课.py` | 主程序（GUI + Playwright 挂机逻辑） |
| `core.py` | 纯逻辑工具（URL/凭据/进度解析、完成判定、时长格式化），可单元测试 |
| `tests/test_units.py` | 单元测试（`unittest`，纯 Python） |
| `demo.ipynb` | Jupyter 展示文件 |
| `账号密码.example.md` | 账号密码占位模板（复制为 `账号密码.md` 后填写） |
| `requirements.txt` | `playwright>=1.40` |
| `.gitignore` | 排除 账号密码.md、session、output、chrome_profile 等 |
