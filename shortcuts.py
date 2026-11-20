"""Keyboard shortcuts that complement the active WeType profile."""

import ctypes as c
from ctypes import wintypes as w

from comtypes import COMError, GUID, HRESULT, IUnknown, STDMETHOD
from comtypes.client import CreateObject

from windows import bind, get_foreground_window, kernel, user


VK_CAPITAL = 0x14
VK_RIGHT = 0x27
LEFT_SHIFT, RIGHT_SHIFT = 0xA0, 0xA1
MODIFIERS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # Shift, Control, Alt, Windows keys
KEY_UP = 0x80
SHORTCUT_MARKER = 0x57545059

get_key_state = bind(user, "GetKeyState", c.c_short, c.c_int)
get_async_key_state = bind(user, "GetAsyncKeyState", c.c_short, c.c_int)
get_module_handle = bind(kernel, "GetModuleHandleW", w.HMODULE, w.LPCWSTR)
HookCallback = c.WINFUNCTYPE(c.c_ssize_t, c.c_int, w.WPARAM, w.LPARAM)
install_hook = bind(user, "SetWindowsHookExW", w.HHOOK, c.c_int, HookCallback, w.HINSTANCE, w.DWORD)
uninstall_hook = bind(user, "UnhookWindowsHookEx", w.BOOL, w.HHOOK)
call_next = bind(user, "CallNextHookEx", c.c_ssize_t, w.HHOOK, c.c_int, w.WPARAM, w.LPARAM)


class InputProfile(c.Structure):
    _fields_ = [
        ("type", w.DWORD), ("language", w.WORD), ("class_id", GUID),
        ("profile_id", GUID), ("category", GUID), ("substitute", w.HANDLE),
        ("capabilities", w.DWORD), ("layout", w.HANDLE), ("flags", w.DWORD),
    ]


class InputProfileManager(IUnknown):
    _iid_ = GUID("{71C6E74C-0F28-11D8-A82A-00065B84435C}")
    # Reserve the preceding slots in the ITfInputProcessorProfileMgr vtable.
    _methods_ = [
        STDMETHOD(HRESULT, name, []) for name in (
            "ActivateProfile", "DeactivateProfile", "GetProfile", "EnumProfiles",
            "ReleaseInputProcessor", "RegisterProfile", "UnregisterProfile",
        )
    ] + [STDMETHOD(HRESULT, "GetActiveProfile", [c.POINTER(GUID), c.POINTER(InputProfile)])]


class WeTypeProfile:
    def __init__(self):
        self.wetype_id = GUID("{86598FB9-66A2-463E-B9C2-AEB906D477AD}")
        self.keyboard_category = GUID("{34745C63-B2F0-4784-8B67-5E12C8701A31}")
        self.manager = CreateObject(
            GUID("{33C53A50-F456-4884-B049-85FD643ECFED}"), interface=InputProfileManager
        )

    def active(self):
        profile = InputProfile()
        try:
            status = self.manager.GetActiveProfile(c.byref(self.keyboard_category), c.byref(profile))
            return status == 0 and profile.class_id == self.wetype_id
        except COMError:
            return False


class KeyboardEvent(c.Structure):
    _fields_ = [
        ("key", w.DWORD), ("scan", w.DWORD), ("flags", w.DWORD),
        ("timestamp", w.DWORD), ("extra", c.c_size_t),
    ]


class KeyboardInput(c.Structure):
    _fields_ = [
        ("key", w.WORD), ("scan", w.WORD), ("flags", w.DWORD),
        ("timestamp", w.DWORD), ("extra", c.c_size_t),
    ]


class MouseInput(c.Structure):
    # The unused mouse member supplies the size and alignment of the Win32 INPUT union.
    _fields_ = [
        ("x", w.LONG), ("y", w.LONG), ("data", w.DWORD), ("flags", w.DWORD),
        ("timestamp", w.DWORD), ("extra", c.c_size_t),
    ]


class InputData(c.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(c.Structure):
    _fields_ = [("type", w.DWORD), ("data", InputData)]


send_input = bind(user, "SendInput", w.UINT, w.UINT, c.POINTER(Input), c.c_int)


def send_key(key, presses=1):
    extended = 0x0001 if key == VK_RIGHT else 0
    key_up = 0x0002
    down = Input(1, InputData(keyboard=KeyboardInput(key, 0, extended, 0, SHORTCUT_MARKER)))
    up = Input(1, InputData(keyboard=KeyboardInput(key, 0, extended | key_up, 0, SHORTCUT_MARKER)))
    events = (Input * (presses * 2))(*([down, up] * presses))
    return send_input(len(events), events, c.sizeof(Input))


def caps_locked():
    return bool(get_key_state(VK_CAPITAL) & 1)


def any_held(keys):
    return any(get_async_key_state(key) & 0x8000 for key in keys)


class KeyboardShortcuts:
    def __init__(self, on_shift_tap, right_steps, invalidate_preview):
        self.on_shift_tap = on_shift_tap
        self.right_steps = right_steps
        self.invalidate_preview = invalidate_preview
        self.shift_enabled = True
        self.shift_tap = None
        self.right_replaced = False
        self.callback = HookCallback(self.handle)
        self.handle_id = install_hook(13, self.callback, get_module_handle(None), 0)  # WH_KEYBOARD_LL
        if not self.handle_id:
            raise c.WinError(c.get_last_error())

    def close(self):
        uninstall_hook(self.handle_id)

    def handle(self, code, message, data):
        if code == 0:
            event = c.cast(data, c.POINTER(KeyboardEvent)).contents
            if event.extra != SHORTCUT_MARKER and self.process(event.key, bool(event.flags & KEY_UP)):
                return 1
        return call_next(None, code, message, data)

    def process(self, key, released):
        if key in (LEFT_SHIFT, RIGHT_SHIFT):
            self.track_shift(key, released)
            return False
        if released:
            replaced = key == VK_RIGHT and self.right_replaced
            if replaced:
                self.right_replaced = False
            return replaced

        self.shift_tap = None
        steps = self.right_steps() if key == VK_RIGHT and not any_held(MODIFIERS) else 1
        self.invalidate_preview()
        if steps > 1 and send_key(VK_RIGHT, steps):
            self.right_replaced = True
            return True
        return False

    def track_shift(self, key, released):
        if released:
            previous, self.shift_tap = self.shift_tap, None
            if previous and previous == (key, get_foreground_window()):
                self.on_shift_tap(previous[1])
            return

        other_shift = LEFT_SHIFT if key == RIGHT_SHIFT else RIGHT_SHIFT
        if self.shift_enabled and not any_held(MODIFIERS[1:] + (other_shift,)):
            self.shift_tap = (key, get_foreground_window())
        else:
            self.shift_tap = None
