"""Manage the current user's Startup shortcut for the overlay."""

from pathlib import Path
import sys

from comtypes.client import CreateObject


class StartupShortcut:
    def __init__(self):
        self.shell = CreateObject("WScript.Shell", dynamic=True)
        directory = self.shell.SpecialFolders.Item("Startup")
        if not directory:
            raise FileNotFoundError("找不到当前用户的启动文件夹")
        self.path = Path(directory) / "微信拼音浮窗.lnk"

    def enabled(self):
        return self.path.is_file()

    def set_enabled(self, enabled):
        if not enabled:
            self.path.unlink(missing_ok=True)
            return

        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if not pythonw.is_file():
            raise FileNotFoundError("找不到用于启动浮窗的 pythonw.exe")
        script = Path(__file__).resolve().with_name("overlay.py")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        shortcut = self.shell.CreateShortcut(str(self.path))
        shortcut.TargetPath = str(pythonw)
        shortcut.Arguments = f'"{script}"'
        shortcut.WorkingDirectory = str(script.parent)
        shortcut.WindowStyle = 7  # Minimized
        shortcut.Description = "登录 Windows 时启动微信拼音浮窗"
        shortcut.Save()
        if not self.enabled():
            raise OSError("Windows 未保存启动快捷方式")
