# 微信拼音浮窗

在微信输入法的整排候选词上方显示一行正在输入的拼音，例如 `jin'tian'tian'qi`。输入、退格或选字时，浮窗会跟随候选栏更新或隐藏。

## 换电脑使用

1. 在 Windows 上安装微信输入法，以及带 Tkinter 和 pip 的 Python 3.9 或更新版本。安装 Python 时启用 Python Launcher 或将 Python 加到 `PATH`。
2. 登录 GitHub，克隆本仓库，或在仓库页面选择 **Code → Download ZIP** 并解压。
3. 双击 `启动拼音浮窗.cmd`。首次启动会创建本地 `.venv` 并联网安装依赖。随后用微信输入法打字即可。

## 使用

点击任务栏里的「微信拼音浮窗」，可以设置拼音字号、暂停或退出。字号可在 10 到 32 磅之间调整，设置会自动保存。

- **单按 Shift**。使用微信输入法时，Caps Lock 开启则解除大写锁定，同时保留微信输入法原有的中英切换。可以在控制面板关闭解除大写锁定的功能。
- **← / →**。拼音输入过程中按音节移动，红色光标表示实际编辑位置。例如在 `jin'tian'tian'qi` 末尾按 ←，光标会到最后一个 `tian` 后面。继续打字或按退格即可在该位置修改。

已在 Windows 11 和微信输入法 `3.0.2.44` 上实测。浮窗只在候选栏可见时，通过 Windows 的文字接口读取当前尚未确认的拼音。拼音在本机临时使用，密码框会跳过。光标显示和增强右键跳转需要输入框向 Windows 提供当前的编辑位置。其他版本的微信输入法若修改候选窗口类名，需要更新 `windows.py` 中的查找逻辑。

## 修改源码

| 文件 | 用途 |
| --- | --- |
| `overlay.py` | 拼音浮窗、红色光标和字号面板 |
| `composition.py` | 读取当前拼音与光标位置，计算音节边界 |
| `shortcuts.py` | 单按 Shift 解除大写锁定及按音节右移 |
| `windows.py` | 定位微信候选窗，设置浮窗位置 |
| `preferences.py` | 保存本机字号和 Shift 选项 |

开发时可在项目目录内手动准备环境，从终端运行程序，便于查看错误信息。运行前通过面板退出已有实例。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe overlay.py
```
