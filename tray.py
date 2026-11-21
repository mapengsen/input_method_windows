"""Connect the settings window to a Windows notification-area icon."""

import ctypes as c
from ctypes import wintypes as w

from comtypes import GUID

from windows import bind, user


NIM_ADD, NIM_DELETE, NIM_SETVERSION = 0, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 1, 2, 4, 0x80
TRAY_MESSAGE = 0x8000 + 1  # WM_APP + 1
WM_LBUTTONUP, NIN_SELECT, NIN_KEYSELECT = 0x0202, 0x0400, 0x0401
WM_GETICON, ICON_SMALL = 0x007F, 0
IDI_APPLICATION = 32512


class NotifyIconData(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("window", w.HWND), ("id", w.UINT), ("flags", w.UINT),
        ("message", w.UINT), ("icon", w.HICON), ("tip", w.WCHAR * 128),
        ("state", w.DWORD), ("state_mask", w.DWORD), ("info", w.WCHAR * 256),
        ("version", w.UINT), ("title", w.WCHAR * 64), ("info_flags", w.DWORD),
        ("guid", GUID), ("balloon_icon", w.HICON),
    ]


shell = c.WinDLL("shell32", use_last_error=True)
controls = c.WinDLL("comctl32", use_last_error=True)
WindowProc = c.WINFUNCTYPE(c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM, c.c_size_t, c.c_size_t)
notify_icon = bind(shell, "Shell_NotifyIconW", w.BOOL, w.DWORD, c.POINTER(NotifyIconData))
set_subclass = bind(controls, "SetWindowSubclass", w.BOOL, w.HWND, WindowProc, c.c_size_t, c.c_size_t)
remove_subclass = bind(controls, "RemoveWindowSubclass", w.BOOL, w.HWND, WindowProc, c.c_size_t)
default_subclass = bind(controls, "DefSubclassProc", c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
register_message = bind(user, "RegisterWindowMessageW", w.UINT, w.LPCWSTR)
send_message = bind(user, "SendMessageW", c.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
load_icon = bind(user, "LoadIconW", w.HICON, w.HINSTANCE, c.c_void_p)


class TrayIcon:
    def __init__(self, window, tooltip):
        self.data = NotifyIconData()
        self.data.size = c.sizeof(NotifyIconData)
        self.data.window = window
        self.data.id = 1
        self.data.flags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        self.data.message = TRAY_MESSAGE
        self.data.icon = send_message(window, WM_GETICON, ICON_SMALL, 0) or load_icon(None, IDI_APPLICATION)
        self.data.tip = tooltip
        self.data.version = 4
        self.taskbar_created = register_message("TaskbarCreated")
        self.visible = False
        self.restore_pending = False
        self.recreate_pending = False
        self.callback = WindowProc(self.handle_message)
        if not set_subclass(window, self.callback, 1, 0):
            raise OSError("无法连接系统托盘")

    def handle_message(self, window, message, wparam, lparam, _subclass, _reference):
        # Tk calls run on the UI timer, outside this native window callback.
        if message == TRAY_MESSAGE:
            if (lparam & 0xFFFF) in (WM_LBUTTONUP, NIN_SELECT, NIN_KEYSELECT):
                self.restore_pending = True
            return 0
        if message == self.taskbar_created and self.visible:
            self.recreate_pending = True
        return default_subclass(window, message, wparam, lparam)

    def show(self):
        if not self.visible:
            self.visible = bool(notify_icon(NIM_ADD, c.byref(self.data)))
            if self.visible:
                notify_icon(NIM_SETVERSION, c.byref(self.data))
        return self.visible

    def hide(self):
        if self.visible:
            notify_icon(NIM_DELETE, c.byref(self.data))
            self.visible = False
        self.restore_pending = self.recreate_pending = False

    def should_restore(self):
        if self.restore_pending:
            return True
        if self.recreate_pending:
            self.recreate_pending = self.visible = False
            # Restore the window if Explorer cannot recreate the icon.
            return not self.show()
        return False

    def close(self):
        self.hide()
        remove_subclass(self.data.window, self.callback, 1)
