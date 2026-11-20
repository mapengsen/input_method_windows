"""Show the current composition on one line above WeType's candidate window."""

import tkinter as tk
from tkinter import font, messagebox, ttk
from time import monotonic

from comtypes import COMError

from composition import CompositionReader
from preferences import MAX_FONT, MIN_FONT, Preferences
from shortcuts import KeyboardShortcuts, VK_CAPITAL, WeTypeProfile, caps_locked, send_key
import windows


class Overlay:
    def __init__(self, root):
        self.window = tk.Toplevel(root, takefocus=False)
        self.window.title("微信拼音预览")
        self.window.overrideredirect(True)
        self.window.attributes("-transparentcolor", "#ff00fd")
        self.font = font.Font(root=root, family="Segoe UI", size=-17, weight="bold")
        self.canvas = tk.Canvas(
            self.window, width=1, height=1, background="#fff8e9",
            highlightbackground="#e7d6b6", highlightthickness=1, borderwidth=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.window.update_idletasks()
        self.hwnd = windows.configure_overlay(self.window.winfo_id())
        self.placement = None
        windows.hide_overlay(self.hwnd)

    def hide(self):
        if self.placement is not None:
            windows.hide_overlay(self.hwnd)
            self.placement = None

    def draw(self, candidate, preview, font_size):
        placement = (candidate, preview, font_size)
        if placement == self.placement:
            return

        dpi = windows.get_dpi(candidate.hwnd) or 96
        self.font.configure(size=-round(font_size * dpi / 72))
        height = self.font.metrics("linespace") + 9
        y = candidate.top - height - 2
        monitor = windows.monitor_bounds(candidate)
        x = candidate.left
        width = max(candidate.width, self.font.measure(preview.text) + 24)
        if monitor is not None:
            if y < monitor.top:
                self.hide()
                return
            x = max(x, monitor.left)
            width = min(width, monitor.right - x)

        if width <= 0:
            self.hide()
            return

        self.canvas.delete("all")
        padding = 11
        text_x = padding
        if preview.caret is not None:
            caret_x = self.font.measure(preview.text[:preview.caret])
            text_x -= max(0, caret_x + 2 * padding - width)
        self.canvas.create_text(text_x, height / 2, text=preview.text, font=self.font, anchor="w", fill="#244aa2")
        if preview.caret is not None:
            caret_x += text_x + 2
            self.canvas.create_line(caret_x, 4, caret_x, height - 4, fill="#d93b32", width=2)
        windows.show_overlay(self.hwnd, x, y, width, height)
        self.placement = placement


class Application:
    def __init__(self, root):
        self.root = root
        self.root.withdraw()
        self.root.title("微信拼音浮窗")
        self.reader = CompositionReader()
        self.preferences = Preferences.load()
        self.preview_state = None
        self.pending_shift_window = None
        self.paused = False
        self.overlay = Overlay(root)
        self.keyboard = None
        try:
            self.wetype_profile = WeTypeProfile()
            self.keyboard = KeyboardShortcuts(self.shift_tapped, self.right_steps, self.invalidate_preview)
            self.keyboard.shift_enabled = self.preferences.shift_caps
        except (COMError, OSError):
            self.wetype_profile = None

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        self.status = tk.StringVar(value=self.active_status())
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(0, 12))

        font_row = ttk.Frame(frame)
        font_row.pack(fill="x")
        ttk.Label(font_row, text="拼音字号").pack(side="left", padx=(0, 8))
        self.font_size = tk.IntVar(value=self.preferences.font_size)
        ttk.Spinbox(
            font_row, from_=MIN_FONT, to=MAX_FONT, width=5, state="readonly",
            textvariable=self.font_size, command=self.change_font_size,
        ).pack(side="left")
        ttk.Label(font_row, text="磅").pack(side="left", padx=(6, 0))
        sample = "jin'tian'tian'qi"
        self.sample_font = font.Font(root=root, family="Segoe UI", size=MAX_FONT, weight="bold")
        sample_frame = ttk.Frame(
            frame, width=self.sample_font.measure(sample) + 8,
            height=self.sample_font.metrics("linespace") + 8,
        )
        sample_frame.pack(fill="x", pady=(6, 12))
        sample_frame.pack_propagate(False)
        self.sample_font.configure(size=self.font_size.get())
        ttk.Label(sample_frame, text=sample, font=self.sample_font, foreground="#244aa2").pack(side="left")

        self.shift_enabled = tk.BooleanVar(value=self.preferences.shift_caps)
        self.shift_option = ttk.Checkbutton(
            frame, text="单按 Shift 时解除大写锁定", variable=self.shift_enabled,
            command=self.change_shift_shortcut,
        )
        self.shift_option.pack(anchor="w", pady=(0, 12))
        if self.keyboard is None:
            self.shift_option.state(["disabled"])

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.toggle = ttk.Button(buttons, text="暂停", command=self.toggle_pause)
        self.toggle.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="退出", command=root.destroy).pack(side="left")

        self.root.update_idletasks()
        width, height = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        self.root.minsize(width, height)
        self.root.geometry(f"{width}x{height}")
        self.root.deiconify()
        self.root.after(55, self.refresh)
        if self.keyboard is not None:
            self.root.after(15, self.apply_pending_shift)

    def active_status(self):
        return "已开启 · 显示正在输入的拼音" if self.keyboard else "拼音预览已开启 · 键盘增强不可用"

    def save_preferences(self):
        try:
            self.preferences.save()
        except OSError:
            self.status.set("本次调整已生效 · 设置保存失败")

    def change_font_size(self):
        self.preferences.font_size = self.font_size.get()
        self.sample_font.configure(size=self.preferences.font_size)
        self.save_preferences()

    def change_shift_shortcut(self):
        self.preferences.shift_caps = self.shift_enabled.get()
        self.keyboard.shift_enabled = self.preferences.shift_caps and not self.paused
        self.save_preferences()

    def invalidate_preview(self):
        self.preview_state = None

    def right_steps(self):
        if self.preview_state:
            foreground, candidate, preview, observed_at = self.preview_state
            if (monotonic() - observed_at < 0.2 and foreground == windows.get_foreground_window()
                    and candidate == windows.find_candidate()):
                return preview.right_steps()
        return 1

    def shift_tapped(self, foreground):
        # The native keyboard hook can run inside Tk's Windows message pump.
        self.pending_shift_window = foreground

    def apply_pending_shift(self):
        foreground, self.pending_shift_window = self.pending_shift_window, None
        if foreground:
            self.unlock_caps(foreground)
        self.root.after(15, self.apply_pending_shift)

    def unlock_caps(self, foreground):
        if (not self.paused and self.preferences.shift_caps and caps_locked()
                and foreground == windows.get_foreground_window() and self.wetype_profile.active()
                and not self.reader.is_password_field() and foreground == windows.get_foreground_window()):
            send_key(VK_CAPITAL)

    def toggle_pause(self):
        self.paused = not self.paused
        self.toggle.configure(text="继续" if self.paused else "暂停")
        self.status.set("已暂停" if self.paused else self.active_status())
        if self.keyboard is not None:
            self.keyboard.shift_enabled = self.preferences.shift_caps and not self.paused
        if self.paused:
            self.overlay.hide()
            self.invalidate_preview()

    def refresh(self):
        candidate = None if self.paused else windows.find_candidate()
        if candidate is None:
            self.overlay.hide()
            self.invalidate_preview()
        else:
            foreground = windows.get_foreground_window()
            preview = self.reader.current_preview()
            if preview and foreground == windows.get_foreground_window() and candidate == windows.find_candidate():
                self.preview_state = (foreground, candidate, preview, monotonic())
                self.overlay.draw(candidate, preview, self.preferences.font_size)
            else:
                self.overlay.hide()
                self.invalidate_preview()
        self.root.after(55 if candidate else 110, self.refresh)


def main():
    instance = windows.single_instance()
    if instance is None:
        return
    try:
        windows.enable_per_monitor_dpi()
        root = tk.Tk()
        try:
            app = Application(root)
        except (COMError, OSError) as error:
            root.withdraw()
            messagebox.showerror("微信拼音浮窗", f"无法启动系统的文字读取接口。\n{error}", parent=root)
            root.destroy()
            return
        try:
            root.mainloop()
        finally:
            if app.keyboard is not None:
                app.keyboard.close()
    finally:
        windows.close_handle(instance)


if __name__ == "__main__":
    main()
