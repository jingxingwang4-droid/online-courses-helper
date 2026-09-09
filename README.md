# 知网学术大讲堂 · 网课挂机助手（Online Courses Watcher）

一个 Windows 下可无人值守、自动观看**知网学术大讲堂**在线课程回放的小工具。
它打开专用浏览器、自动登录、逐门打开课程，**1 倍速真实播放**，并绕过"浏览器必须在台前"的限制，
用 GUI 实时显示每门课进度与累计学习时长。

> ⚠️ 项目仅供学习自动化与 Playwright / 浏览器自动化研究。
> 请遵守平台规则与课程要求，勿用于违规用途。请勿公开本人真实账号密码，务必自行更换示例中的占位符。

## 功能

- 自动读取 `账号密码.md` 中的账号密码并登录（首次需要手动拖一次滑块验证，之后浏览器保存登录态自动登录）。
- 自动报名 / 逐门打开课程回放，**1 倍速真实播放**，播放完自动切换下一门。
- 绕过"窗口必须在台前"的检测：最小化或被遮挡也能正常计时。
- 以 **服务端 `course/list` 接口** 为准判断"已学完/进度"，而非视频 `currentTime`。
- 进度自动存盘 `progress.json`，中断后可继续；全部分完之后进入"循环补学"轮换观看回放。
- GUI 监控器：开始 / 暂停 / 继续 / 停止，实时显示每门进度、总进度、预计剩余时间、累计学习时长。

## 原理（如何绕过台前检测）

1. 给每个页面注入脚本，伪造：
   - `document.visibilityState = 'visible'`、`document.hidden = false`、`document.hasFocus() = true`
   - 拦截 `visibilitychange / blur` 事件，令页面始终认为自己处于前台。
2. Chrome 启动参数禁用后台节流/遮挡检测（见 `PLAYER_FLAGS`）。
3. CDP 层开启焦点模拟与 `Page.setWebLifecycleState('active')`，防止页面被冻结。

```python
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
```

## 环境与运行

需要 Python 3.9+，以及系统安装的 Chrome/Chromium。

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 安装 Playwright 的浏览器驱动
playwright install chromium

# 3) 准备账号
cp 账号密码.example.md 账号密码.md   # Windows: copy 账号密码.example.md 账号密码.md
#    然后编辑 账号密码.md，把占位符换成你自己的账号密码

# 4) 运行
python 刷网课.py
```

> Windows 双击运行：可建一个 `.bat`，如：
> `start "" "pythonw.exe" 刷网课.py`（或把 `python.exe` 换成你的解释器即可）。

## 使用

1. 运行后点击 **开始学习**。
2. 首次登录会弹出滑块验证，**手动拖一次即可**；之后自动登录。
3. 浏览器窗口可最小化 / 被完全遮挡；请勿让电脑休眠（建议插电）。
4. 随时可 **暂停 / 继续 / 停止**；进度保存在 `progress.json`。

## 文件

| 文件 | 说明 |
|---|---|
| `刷网课.py` | 主程序（GUI + 挂机逻辑） |
| `requirements.txt` | Python 依赖（`playwright>=1.40`） |
| `demo.ipynb` | Jupyter 展示文件（演示原理、运行示例） |
| `账号密码.example.md` | 账号密码占位模板（请复制为 `账号密码.md` 后填写） |
| `.gitignore` | 排除凭据、会话、生成产物 |

## 说明

- 站点规定快进/倍速/暂停不计时长，因此脚本全程 **1 倍速真实播放**，不会快进。
- 六门课总时长约 15+ 小时，建议分几天挂完（进度保留）。
- 若遇考试 / 测验弹窗，脚本不会乱点，会在日志提示，需要你手动处理。
