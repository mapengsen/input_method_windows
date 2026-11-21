"""Store the user's display and keyboard preferences between launches."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


MIN_FONT = 10
MAX_FONT = 32
SETTINGS = Path(os.environ["LOCALAPPDATA"]) / "WeTypePinyinOverlay" / "settings.json"


@dataclass
class Preferences:
    font_size: int = 12
    shift_caps: bool = True
    close_action: str = "exit"

    @classmethod
    def load(cls):
        preferences = cls()
        try:
            saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return preferences
        if isinstance(saved, dict):
            font_size = saved.get("font_size")
            if type(font_size) is int and MIN_FONT <= font_size <= MAX_FONT:
                preferences.font_size = font_size
            shift_caps = saved.get("shift_caps")
            if isinstance(shift_caps, bool):
                preferences.shift_caps = shift_caps
            close_action = saved.get("close_action")
            if close_action in ("exit", "minimize", "tray"):
                preferences.close_action = close_action
        return preferences

    def save(self):
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        temporary = SETTINGS.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        temporary.replace(SETTINGS)
