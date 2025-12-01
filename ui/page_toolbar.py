"""Toolbar with visibility toggles, tool selection, and zoom controls."""
from __future__ import annotations

from typing import Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from i18n import tr
from ui.tools import PageTool


class PageToolsToolbar(QtWidgets.QWidget):
    """Compact toolbar for page tools and visibility toggles."""

    maskToggled = QtCore.Signal(bool)
    textToggled = QtCore.Signal(bool)
    sfxToggled = QtCore.Signal(bool)
    toolSelected = QtCore.Signal(PageTool)
    colorPickRequested = QtCore.Signal()
    zoomInRequested = QtCore.Signal()
    zoomOutRequested = QtCore.Signal()
    zoomResetRequested = QtCore.Signal()
    zoomFitWidthRequested = QtCore.Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._language: str = "en"
        self._visibility_buttons: Dict[str, QtWidgets.QToolButton] = {}
        self._tool_buttons: Dict[PageTool, QtWidgets.QToolButton] = {}
        self._tooltip_keys: Dict[QtWidgets.QToolButton, str] = {}

        self._build_ui()
        self._apply_labels()

    # -------------------- setup helpers -------------------- #
    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Visibility toggles
        self.btn_mask = self._make_tool_button("🎭", "toolbar.mask_tooltip", checkable=True, checked=True)
        self.btn_text = self._make_tool_button("🅰", "toolbar.text_tooltip", checkable=True, checked=True)
        self.btn_sfx = self._make_tool_button("💥", "toolbar.sfx_tooltip", checkable=True, checked=True)
        for btn in (self.btn_mask, self.btn_text, self.btn_sfx):
            layout.addWidget(btn)

        self.btn_mask.toggled.connect(self.maskToggled)
        self.btn_text.toggled.connect(self.textToggled)
        self.btn_sfx.toggled.connect(self.sfxToggled)
        self._visibility_buttons = {"mask": self.btn_mask, "text": self.btn_text, "sfx": self.btn_sfx}

        # Tool buttons (mutually exclusive)
        layout.addSpacing(4)
        self.tool_group = QtWidgets.QButtonGroup(self)
        self.tool_group.setExclusive(True)
        for tool, emoji, tooltip_key in [
            (PageTool.BRUSH, "🖌️", "toolbar.brush_tooltip"),
            (PageTool.ERASER, "🧽", "toolbar.eraser_tooltip"),
            (PageTool.EYEDROPPER, "🧪", "toolbar.eyedropper_tooltip"),
            (PageTool.HAND, "✋", "toolbar.hand_tooltip"),
        ]:
            btn = self._make_tool_button(emoji, tooltip_key, checkable=True, checked=tool == PageTool.BRUSH)
            self.tool_group.addButton(btn)
            self._tool_buttons[tool] = btn
            layout.addWidget(btn)
        self.tool_group.buttonToggled.connect(self._on_tool_toggled)

        # Color picker
        layout.addSpacing(4)
        self.btn_color = self._make_tool_button("🎨", "toolbar.color_tooltip")
        self.btn_color.clicked.connect(self.colorPickRequested)
        layout.addWidget(self.btn_color)

        # Zoom controls
        layout.addSpacing(4)
        self.btn_zoom_in = self._make_tool_button("➕", "toolbar.zoom_in_tooltip")
        self.btn_zoom_out = self._make_tool_button("➖", "toolbar.zoom_out_tooltip")
        self.btn_zoom_reset = self._make_tool_button("🔁", "toolbar.zoom_reset_tooltip")
        self.btn_zoom_fit_width = self._make_tool_button("📐", "toolbar.zoom_fit_width_tooltip")

        self.btn_zoom_in.clicked.connect(self.zoomInRequested)
        self.btn_zoom_out.clicked.connect(self.zoomOutRequested)
        self.btn_zoom_reset.clicked.connect(self.zoomResetRequested)
        self.btn_zoom_fit_width.clicked.connect(self.zoomFitWidthRequested)

        for btn in (self.btn_zoom_in, self.btn_zoom_out, self.btn_zoom_reset, self.btn_zoom_fit_width):
            layout.addWidget(btn)

        layout.addStretch(1)

    def _make_tool_button(
        self,
        emoji: str,
        tooltip_key: str,
        *,
        checkable: bool = False,
        checked: bool = False,
    ) -> QtWidgets.QToolButton:
        btn = QtWidgets.QToolButton(self)
        btn.setText(emoji)
        btn.setCheckable(checkable)
        if checkable:
            btn.setChecked(checked)
        btn.setAutoRaise(True)
        btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        font = btn.font()
        font.setPointSize(max(font.pointSize() + 2, 10))
        btn.setFont(font)
        btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._tooltip_keys[btn] = tooltip_key
        return btn

    # -------------------- language helpers -------------------- #
    def set_language(self, language: str) -> None:
        """Update tooltips according to the active UI language."""
        self._language = (language or "en").lower()
        self._apply_labels()

    def _apply_labels(self) -> None:
        for btn, tooltip_key in self._tooltip_keys.items():
            if tooltip_key:
                tooltip = tr(tooltip_key, self._language)
                btn.setToolTip(tooltip)
                btn.setStatusTip(tooltip)

    # -------------------- state helpers -------------------- #
    def _on_tool_toggled(self, button: QtWidgets.QAbstractButton, checked: bool) -> None:
        if not checked:
            return
        for tool, btn in self._tool_buttons.items():
            if btn is button:
                self.toolSelected.emit(tool)
                return

    def set_current_tool(self, tool: PageTool) -> None:
        """Update checked state without emitting selection twice."""
        btn = self._tool_buttons.get(tool)
        if btn is None:
            return
        if not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)

    def set_visibility_state(
        self,
        *,
        mask: Optional[bool] = None,
        text: Optional[bool] = None,
        sfx: Optional[bool] = None,
    ) -> None:
        """Sync toggle buttons with external state."""
        if mask is not None:
            self._set_button_checked(self.btn_mask, mask)
        if text is not None:
            self._set_button_checked(self.btn_text, text)
        if sfx is not None:
            self._set_button_checked(self.btn_sfx, sfx)

    def _set_button_checked(self, button: QtWidgets.QToolButton, checked: bool) -> None:
        if button.isChecked() != checked:
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)
