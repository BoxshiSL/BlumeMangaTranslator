from __future__ import annotations

from typing import Dict

from PySide6 import QtCore, QtWidgets


class LayersPanel(QtWidgets.QWidget):
    """Small panel to toggle layer visibility and choose an active layer."""

    layerVisibilityChanged = QtCore.Signal(str, bool)
    activeLayerChanged = QtCore.Signal(str)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._visibility_buttons: Dict[str, QtWidgets.QToolButton] = {}
        self._active_buttons: Dict[str, QtWidgets.QRadioButton] = {}

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        layers = [
            ("background", "Background", False),
            ("mask", "Mask", False),
            ("paint", "Paint", True),
            ("text", "Text", True),
        ]

        for key, label, editable in layers:
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)

            eye_btn = QtWidgets.QToolButton(self)
            eye_btn.setCheckable(True)
            eye_btn.setChecked(True)
            eye_btn.setAutoRaise(True)
            eye_btn.setToolTip(f"Toggle {label} visibility")
            eye_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DesktopIcon))
            eye_btn.toggled.connect(lambda checked, k=key: self.layerVisibilityChanged.emit(k, checked))
            self._visibility_buttons[key] = eye_btn

            radio = QtWidgets.QRadioButton(label, self)
            radio.setEnabled(editable)
            radio.toggled.connect(lambda checked, k=key: checked and self.activeLayerChanged.emit(k))
            self._active_buttons[key] = radio

            row.addWidget(eye_btn)
            row.addWidget(radio)
            row.addStretch(1)
            layout.addLayout(row)

        layout.addStretch(1)

    def set_layer_visible(self, layer: str, visible: bool) -> None:
        btn = self._visibility_buttons.get(layer)
        if btn is None:
            return
        if btn.isChecked() != visible:
            btn.blockSignals(True)
            btn.setChecked(bool(visible))
            btn.blockSignals(False)

    def set_active_layer(self, layer: str) -> None:
        btn = self._active_buttons.get(layer)
        if btn is None:
            return
        if not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
