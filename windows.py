"""Locate the WeType candidate window and place a non-activating overlay above it."""

import ctypes as c
from ctypes import wintypes as w
from dataclasses import dataclass


def bind(library, name, result, *arguments):
    function = getattr(library, name)
    function.argtypes = arguments
    function.restype = result
    return function


user = c.WinDLL("user32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
find_window = bind(user, "FindWindowW", w.HWND, w.LPCWSTR, w.LPCWSTR)
window_visible = bind(user, "IsWindowVisible", w.BOOL, w.HWND)
get_window_rect = bind(user, "GetWindowRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
get_dpi = bind(user, "GetDpiForWindow", w.UINT, w.HWND)
get_foreground_window = bind(user, "GetForegroundWindow", w.HWND)
monitor_from_window = bind(user, "MonitorFromWindow", w.HMONITOR, w.HWND, w.DWORD)
get_monitor_info = bind(user, "GetMonitorInfoW", w.BOOL, w.HMONITOR, c.c_void_p)
get_ancestor = bind(user, "GetAncestor", w.HWND, w.HWND, w.UINT)
get_style = bind(user, "GetWindowLongW", w.LONG, w.HWND, c.c_int)
set_style = bind(user, "SetWindowLongW", w.LONG, w.HWND, c.c_int, w.LONG)
set_position = bind(user, "SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT)
show_window = bind(user, "ShowWindow", w.BOOL, w.HWND, c.c_int)
create_mutex = bind(kernel, "CreateMutexW", w.HANDLE, c.c_void_p, w.BOOL, w.LPCWSTR)
close_handle = bind(kernel, "CloseHandle", w.BOOL, w.HANDLE)


class MonitorInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]


@dataclass(frozen=True)
class CandidateWindow:
    hwnd: int
    left: int
    top: int
    width: int
    height: int


def enable_per_monitor_dpi():
    bind(user, "SetProcessDpiAwarenessContext", w.BOOL, w.HANDLE)(-4)


def single_instance():
    handle = create_mutex(None, False, "Local\\WeTypePinyinOverlay")
    if not handle:
        raise c.WinError(c.get_last_error())
    if c.get_last_error() == 183:
        close_handle(handle)
        return None
    return handle


def find_candidate():
    hwnd = find_window("WeType.NativeCandidate.Direct2D.v2", "WeType Native Candidate")
    rect = w.RECT()
    if hwnd and window_visible(hwnd) and get_window_rect(hwnd, c.byref(rect)):
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width > 0 and height > 0:
            return CandidateWindow(hwnd, rect.left, rect.top, width, height)
    return None


def monitor_bounds(candidate):
    monitor = monitor_from_window(candidate.hwnd, 2)
    info = MonitorInfo(c.sizeof(MonitorInfo))
    if monitor and get_monitor_info(monitor, c.byref(info)):
        return info.monitor
    return None


def configure_overlay(tk_window_id):
    hwnd = get_ancestor(tk_window_id, 2)
    no_activate = 0x08000000
    tool_window = 0x00000080
    transparent = 0x00000020
    set_style(hwnd, -20, get_style(hwnd, -20) | no_activate | tool_window | transparent)
    return hwnd


def show_overlay(hwnd, x, y, width, height):
    no_activate_and_show = 0x0010 | 0x0040
    set_position(hwnd, -1, x, y, width, height, no_activate_and_show)


def hide_overlay(hwnd):
    show_window(hwnd, 0)
