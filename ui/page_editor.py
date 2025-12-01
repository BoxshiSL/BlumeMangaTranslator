"""Table-based editor for page TextBlocks."""
from __future__ import annotations

from typing import List, Optional

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

from i18n import tr
from project.page_session import PageSession, TextBlock


COL_ENABLED = 0
COL_TYPE = 1
COL_ORIGINAL = 2
COL_TRANSLATION = 3
COL_CONFIDENCE = 4


class PageEditor(QtWidgets.QWidget):
    """
    Central editor that displays and edits TextBlocks for the current PageSession.
    Uses the session as the single source of truth (no shadow copies).
    """

    ocrAndTranslateRequested = Signal()
    retranslateSelectedRequested = Signal(list)  # list[str] block ids
    refreshCanvasRequested = Signal()

    translationChanged = Signal(str, str)  # block_id, new_text
    enabledChanged = Signal(str, bool)
    blockTypeChanged = Signal(str, str)
    currentBlockChanged = Signal(str)
    blockDeleted = Signal(str)
    blocksChanged = Signal()

    # Backward-compat signals
    retranslateBlocksRequested = Signal(list)
    blockEnabledChanged = Signal(str, bool)
    addBlockRequested = Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._language: str = "en"
        self._session: Optional[PageSession] = None
        self._suppress_table_signals: bool = False

        self._build_ui()
        self._apply_headers()
        self._apply_labels()

    # -------------------- UI setup --------------------
    def _build_ui(self) -> None:
        self.btn_ocr_translate = QtWidgets.QPushButton(self)
        self.btn_retranslate = QtWidgets.QPushButton(self)
        self.btn_refresh = QtWidgets.QPushButton(self)
        self.btn_add = QtWidgets.QPushButton(self)
        self.btn_delete = QtWidgets.QPushButton(self)

        actions_layout = QtWidgets.QHBoxLayout()
        actions_layout.setContentsMargins(4, 4, 4, 4)
        actions_layout.setSpacing(6)
        actions_layout.addWidget(self.btn_ocr_translate)
        actions_layout.addWidget(self.btn_retranslate)
        actions_layout.addWidget(self.btn_refresh)
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.btn_add)
        actions_layout.addWidget(self.btn_delete)

        self._table = QtWidgets.QTableWidget(self)
        self._table.setColumnCount(5)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(actions_layout)
        layout.addWidget(self._table)

        self.setLayout(layout)

        self.btn_ocr_translate.clicked.connect(self.ocrAndTranslateRequested)
        self.btn_retranslate.clicked.connect(self._emit_retranslate_for_selected_rows)
        self.btn_refresh.clicked.connect(self.refreshCanvasRequested)
        self.btn_add.clicked.connect(self.addBlockRequested)
        self.btn_delete.clicked.connect(self._delete_selected_block)

        self._table.itemChanged.connect(self._on_item_changed)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.selectionModel().currentRowChanged.connect(self._on_current_row_changed)  # type: ignore[arg-type]

    # -------------------- Public API --------------------
    def set_page_session(self, session: PageSession) -> None:
        """Bind PageSession and rebuild the table from its blocks."""
        self._session = session
        self._rebuild_table_from_session()

    def set_language(self, lang: str) -> None:
        """Update UI texts according to language code."""
        self._language = (lang or "en").lower()
        self._apply_headers()
        self._apply_labels()
        self._rebuild_table_from_session()

    def get_blocks(self) -> List[TextBlock]:
        """Return non-deleted blocks from the bound session."""
        if self._session is None:
            return []
        return [b for b in self._session.text_blocks if not getattr(b, "deleted", False)]

    def focus_translation_cell_for_block(self, block_id: str) -> None:
        """Select and edit the translation cell for the specified block id."""
        row = self._row_for_block_id(block_id)
        if row is None:
            return
        self._table.setCurrentCell(row, COL_TRANSLATION)
        item_tr = self._table.item(row, COL_TRANSLATION)
        if item_tr is not None:
            self._table.editItem(item_tr)

    def select_block_by_id(self, block_id: str) -> None:
        """Programmatically select the row for the given block id."""
        row = self._row_for_block_id(block_id)
        if row is None:
            return
        self._suppress_table_signals = True
        self._table.selectRow(row)
        self._suppress_table_signals = False
        self.currentBlockChanged.emit(block_id)

    # -------------------- Internal helpers --------------------
    def _visible_blocks(self) -> List[TextBlock]:
        if self._session is None:
            return []
        return [b for b in self._session.text_blocks if not getattr(b, "deleted", False)]

    def _block_id_for_row(self, row: int) -> Optional[str]:
        item = self._table.item(row, COL_ORIGINAL)
        return item.data(Qt.UserRole) if item is not None else None

    def _row_for_block_id(self, block_id: str) -> Optional[int]:
        for row in range(self._table.rowCount()):
            if self._block_id_for_row(row) == block_id:
                return row
        return None

    def _find_block(self, block_id: str) -> Optional[TextBlock]:
        if self._session is None:
            return None
        for block in self._session.text_blocks:
            if block.id == block_id:
                return block
        return None

    def _rebuild_table_from_session(self) -> None:
        blocks = self._visible_blocks()
        self._suppress_table_signals = True
        self._table.blockSignals(True)
        self._table.clearContents()
        self._table.setRowCount(len(blocks))

        for row, block in enumerate(blocks):
            enabled_item = QtWidgets.QTableWidgetItem()
            enabled_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            enabled_item.setCheckState(Qt.CheckState.Checked if block.enabled else Qt.CheckState.Unchecked)
            enabled_item.setData(Qt.UserRole, block.id)
            self._table.setItem(row, COL_ENABLED, enabled_item)

            type_combo = QtWidgets.QComboBox(self._table)
            type_combo.addItem(tr("block_type.dialog", self._language), userData="dialog")
            type_combo.addItem(tr("block_type.narration", self._language), userData="narration")
            type_combo.addItem(tr("block_type.sfx", self._language), userData="sfx")
            type_combo.addItem(tr("block_type.system", self._language), userData="system")
            idx = type_combo.findData(block.block_type)
            type_combo.setCurrentIndex(idx if idx >= 0 else 0)
            type_combo.setProperty("block_id", block.id)
            type_combo.currentIndexChanged.connect(self._on_type_changed)
            self._table.setCellWidget(row, COL_TYPE, type_combo)

            orig_item = QtWidgets.QTableWidgetItem(block.original_text)
            orig_item.setFlags(orig_item.flags() & ~Qt.ItemIsEditable)
            orig_item.setToolTip(block.original_text)
            orig_item.setData(Qt.UserRole, block.id)
            self._table.setItem(row, COL_ORIGINAL, orig_item)

            tr_item = QtWidgets.QTableWidgetItem(block.translated_text or "")
            tr_item.setData(Qt.UserRole, block.id)
            self._table.setItem(row, COL_TRANSLATION, tr_item)

            conf_item = QtWidgets.QTableWidgetItem(f"{float(block.confidence):.2f}")
            conf_item.setFlags(conf_item.flags() & ~Qt.ItemIsEditable)
            conf_item.setData(Qt.UserRole, block.id)
            self._table.setItem(row, COL_CONFIDENCE, conf_item)

        self._table.resizeColumnsToContents()
        self._table.blockSignals(False)
        self._suppress_table_signals = False

    # -------------------- Slots --------------------
    def _on_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._suppress_table_signals or item is None:
            return
        block_id = item.data(Qt.UserRole)
        block = self._find_block(block_id)
        if block is None:
            return

        if item.column() == COL_TRANSLATION:
            new_text = item.text()
            block.translated_text = new_text
            self.translationChanged.emit(block_id, new_text)
        elif item.column() == COL_ENABLED:
            enabled = item.checkState() == Qt.CheckState.Checked
            if block.enabled != enabled:
                block.enabled = enabled
                self.enabledChanged.emit(block_id, enabled)
                self.blockEnabledChanged.emit(block_id, enabled)

        self.blocksChanged.emit()

    def _on_type_changed(self, index: int) -> None:
        if self._suppress_table_signals:
            return
        combo = self.sender()
        if not isinstance(combo, QtWidgets.QComboBox):
            return
        block_id = combo.property("block_id")
        if not block_id:
            return
        block = self._find_block(block_id)
        if block is None:
            return
        new_type = combo.currentData() or combo.currentText()
        if block.block_type == new_type:
            return
        block.block_type = str(new_type)
        self.blockTypeChanged.emit(block_id, block.block_type)
        self.blocksChanged.emit()

    def _on_current_row_changed(self, current: QtCore.QModelIndex, _previous: QtCore.QModelIndex) -> None:
        if self._suppress_table_signals:
            return
        if not current.isValid():
            return
        block_id = self._block_id_for_row(current.row())
        if block_id:
            self.currentBlockChanged.emit(block_id)

    def _delete_selected_block(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        block_id = self._block_id_for_row(row)
        if not block_id:
            return
        block = self._find_block(block_id)
        if block is not None:
            block.deleted = True
        self._rebuild_table_from_session()
        self.blockDeleted.emit(block_id)
        self.blocksChanged.emit()

    # -------------------- Context menu --------------------
    def _show_context_menu(self, pos: QtCore.QPoint) -> None:
        global_pos = self._table.viewport().mapToGlobal(pos)
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        if not self._table.selectionModel().isRowSelected(row):
            self._table.selectRow(row)

        menu = QtWidgets.QMenu(self)
        action_retranslate = menu.addAction(tr("editor.retranslate_selected", self._language))
        action_delete = menu.addAction(tr("editor.delete_block", self._language))
        action = menu.exec(global_pos)
        if action is action_retranslate:
            self._emit_retranslate_for_selected_rows()
        elif action is action_delete:
            self._delete_selected_block()

    def _emit_retranslate_for_selected_rows(self) -> None:
        selected_rows = self._table.selectionModel().selectedRows()
        if not selected_rows:
            return
        ids: List[str] = []
        for model_index in selected_rows:
            block_id = self._block_id_for_row(model_index.row())
            if block_id:
                ids.append(block_id)
        if ids:
            self.retranslateSelectedRequested.emit(ids)
            self.retranslateBlocksRequested.emit(ids)

    # -------------------- Labels --------------------
    def _apply_headers(self) -> None:
        headers = [
            tr("table.enabled", self._language),
            tr("table.type", self._language),
            tr("table.original", self._language),
            tr("table.translation", self._language),
            tr("table.confidence", self._language),
        ]
        self._table.setHorizontalHeaderLabels(headers)

    def _apply_labels(self) -> None:
        self.btn_ocr_translate.setText(tr("editor.ocr_page", self._language))
        self.btn_retranslate.setText(tr("editor.retranslate_selected", self._language))
        self.btn_refresh.setText(tr("editor.refresh_canvas", self._language))
        self.btn_add.setText(tr("editor.add_block", self._language))
        self.btn_delete.setText(tr("editor.delete_block", self._language))
