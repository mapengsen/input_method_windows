"""Read the active IME composition from the focused control, if it exposes it."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from comtypes import COMError
from comtypes.client import CreateObject, GetModule


PINYIN_TAIL = re.compile(r"[A-Za-zÜü](?:[A-Za-zÜü'’ ;\-]*[A-Za-zÜü'’]|$)$")
SYLLABLE = re.compile(r"[A-Za-zÜü]+")
START, END = 0, 1  # TextPatternRangeEndpoint values


@dataclass(frozen=True)
class PinyinPreview:
    text: str
    caret: int | None

    def right_steps(self):
        if self.caret is None:
            return 1
        for syllable in SYLLABLE.finditer(self.text):
            if syllable.end() > self.caret:
                return syllable.end() - max(self.caret, syllable.start())
        return 1


class CompositionReader:
    def __init__(self):
        self.uia = GetModule(os.path.join(os.environ["WINDIR"], "System32", "UIAutomationCore.dll"))
        self.automation = CreateObject(self.uia.CUIAutomation8, interface=self.uia.IUIAutomation2)
        self.automation.ConnectionTimeout = 250
        self.automation.TransactionTimeout = 250

    def is_password_field(self):
        try:
            element = self.automation.GetFocusedElement()
            return not element or bool(element.CurrentIsPassword)
        except COMError:
            return True

    def current_preview(self):
        try:
            element = self.automation.GetFocusedElement()
            if not element or element.CurrentIsPassword:
                return None
            pattern = element.GetCurrentPattern(self.uia.UIA_TextEditPatternId)
            if not pattern:
                return None
            composition = pattern.QueryInterface(self.uia.IUIAutomationTextEditPattern).GetActiveComposition()
            if not composition:
                return None
            source = composition.GetText(256).rstrip()
        except COMError:
            # Focus or the active composition can vanish during the query.
            return None

        match = PINYIN_TAIL.search(source)
        if not match:
            return None
        caret = self.caret_offset(element, composition, source)
        relative_caret = None if caret is None else max(0, caret - match.start())
        return PinyinPreview(match.group(0), relative_caret)

    def caret_offset(self, element, composition, source):
        try:
            pattern = element.GetCurrentPattern(self.uia.UIA_TextPatternId)
            if not pattern:
                return None
            selections = pattern.QueryInterface(self.uia.IUIAutomationTextPattern).GetSelection()
            if not selections or selections.Length != 1:
                return None
            caret = selections.GetElement(0)
            if caret.CompareEndpoints(END, composition, START) < 0 or caret.CompareEndpoints(END, composition, END) > 0:
                return None
            prefix = composition.Clone()
            prefix.MoveEndpointByRange(END, caret, END)
            text = prefix.GetText(256)
            if source.startswith(text):
                return len(text)
        except COMError:
            return None
        return None
