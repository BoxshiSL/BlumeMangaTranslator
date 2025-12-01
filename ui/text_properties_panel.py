from __future__ import annotations

from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets


class TextPropertiesPanel(QtWidgets.QWidget):
    """Panel for per-bubble text styling."""

    fontChanged = QtCore.Signal(object)
    sizeChanged = QtCore.Signal(object)
    alignChanged = QtCore.Signal(object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QFormLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.font_combo = QtWidgets.QComboBox(self)
        self.font_combo.addItem("Default", None)
        for family in sorted(QtGui.QFontDatabase().families()):
            self.font_combo.addItem(family, family)
        self.font_combo.currentIndexChanged.connect(self._emit_font_changed)
        layout.addRow("Font", self.font_combo)

        self.size_spin = QtWidgets.QSpinBox(self)
        self.size_spin.setRange(0, 96)
        self.size_spin.setSpecialValueText("Default")
        self.size_spin.setValue(0)
        self.size_spin.valueChanged.connect(self._emit_size_changed)
        layout.addRow("Size", self.size_spin)

        self.align_combo = QtWidgets.QComboBox(self)
        self.align_combo.addItem("Center", None)
        self.align_combo.addItem("Left", "left")
        self.align_combo.addItem("Right", "right")
        self.align_combo.currentIndexChanged.connect(self._emit_align_changed)
        layout.addRow("Align", self.align_combo)

        layout.addItem(QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Expanding))

    def set_properties(self, font_family: Optional[str], font_size: Optional[int], align: Optional[str]) -> None:
        self._set_combo_value(self.font_combo, font_family)
        self._set_spin_value(self.size_spin, font_size)
        self._set_combo_value(self.align_combo, align)

    def _set_combo_value(self, combo: QtWidgets.QComboBox, value: Optional[str]) -> None:
        data_value = value if value else None
        idx = combo.findData(data_value)
        if idx < 0:
            idx = 0
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _set_spin_value(self, spin: QtWidgets.QSpinBox, value: Optional[int]) -> None:
        target = 0 if value is None else int(value)
        spin.blockSignals(True)
        spin.setValue(target)
        spin.blockSignals(False)

    def _emit_font_changed(self) -> None:
        self.fontChanged.emit(self.font_combo.currentData())

    def _emit_size_changed(self, value: int) -> None:
        self.sizeChanged.emit(None if value == 0 else int(value))

    def _emit_align_changed(self) -> None:
        self.alignChanged.emit(self.align_combo.currentData())
