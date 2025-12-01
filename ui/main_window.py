"""Main application window for Blume Manga Translator."""
from __future__ import annotations

import uuid
from pathlib import Path
import copy
from typing import Any, Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from config import APP_NAME, SESSIONS_SUBDIR, app_config
from core.engines_registry import ENGINE_BY_ID, EngineConfig, normalize_engine_id
from export.image_export import export_page_with_translations
from knowledge.context_manager import ContextManager
from ocr.engine import OcrEngine
from project.loader import open_project_from_folder, save_project_meta
from project.models import PageInfo, TitleProject
from project.normalizer import (
    compute_resolution_stats,
    get_normalized_image_path,
    migrate_session_geometry,
)
from project.resolution_presets import get_preset_by_id
from project.page_session import PageSession, TextBlock, infer_block_type, infer_orientation, ocr_blocks_to_text_blocks
from project.session_io import load_page_session, save_page_session
from project.utils import load_image_as_np
from i18n import tr
from settings_manager import load_effective_settings
from translator.registry import get_translator_engine_config, normalize_translator_id
from translator.rate_limiter import consume_slow_mode_notice, is_slow_mode
from translator.service import TranslationService
from export.builder import build_export_page_data
from export.openraster import export_page_to_openraster
from ui.dialogs import ResolutionSuggestionDialog, SettingsDialog, TitleSettingsDialog
from ui.page_editor import PageEditor
from ui.page_viewer import PageViewerPanel
from ui.translated_canvas import TranslatedPageCanvas
from ui.page_toolbar import PageToolsToolbar
from ui.layers_panel import LayersPanel
from ui.text_properties_panel import TextPropertiesPanel
from ui.tools import ActiveLayer, PageTool


class SessionHistory:
    """Simple undo/redo stack for per-page session snapshots."""

    def __init__(self, max_depth: int = 50) -> None:
        self.max_depth = max_depth
        self._undo: list[PageSession] = []
        self._redo: list[PageSession] = []

    def _clone(self, session: PageSession) -> PageSession:
        temp_image = getattr(session, "paint_layer_image", None)
        temp_blocks_images: list[tuple[object, object]] = []
        try:
            if isinstance(temp_image, QtGui.QImage):
                session.paint_layer_image = None
            for block in getattr(session, "text_blocks", []):
                if hasattr(block, "paint_layer_image") and isinstance(getattr(block, "paint_layer_image"), QtGui.QImage):
                    temp_blocks_images.append((block, block.paint_layer_image))
                    block.paint_layer_image = None
            clone = copy.deepcopy(session)
        finally:
            if isinstance(temp_image, QtGui.QImage):
                session.paint_layer_image = temp_image
            for block, img in temp_blocks_images:
                block.paint_layer_image = img
        # Drop heavy/non-picklable GUI artifacts on the clone as well
        for block in getattr(clone, "text_blocks", []):
            if hasattr(block, "paint_layer_image"):
                setattr(block, "paint_layer_image", None)
        if hasattr(clone, "paint_layer_image"):
            clone.paint_layer_image = None
        return clone

    def reset(self, session: PageSession) -> None:
        self._undo = [self._clone(session)]
        self._redo = []

    def push(self, session: PageSession) -> None:
        self._undo.append(self._clone(session))
        if len(self._undo) > self.max_depth:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return len(self._undo) > 1

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Optional[PageSession]:
        if not self.can_undo():
            return None
        current = self._undo.pop()
        self._redo.append(current)
        return self._clone(self._undo[-1])

    def redo(self) -> Optional[PageSession]:
        if not self._redo:
            return None
        session = self._redo.pop()
        self._undo.append(self._clone(session))
        return self._clone(session)


class MainWindow(QtWidgets.QMainWindow):
    """
    Main window for Blume Manga Translator. Handles project loading, OCR/translation
    pipeline, navigation, mask rendering, and session persistence.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)

        self.current_project: Optional[TitleProject] = None
        self.current_page_index: int = 0
        self.context_manager: ContextManager = ContextManager()
        self.translation_service: TranslationService = TranslationService(self.context_manager)
        self.translation_service.set_rate_limit_callback(self._on_rate_limit_activated)
        self.page_sessions: Dict[int, PageSession] = {}
        self.current_session_dirty: bool = False
        self._history = SessionHistory()
        self._applying_history: bool = False
        self.show_translation_mask: bool = True
        self.current_tool: PageTool = PageTool.BRUSH
        self._active_view: str = "translated"
        self._layout_initialized: bool = False
        self.settings_cache: Dict[str, Any] = load_effective_settings(None)

        self._init_actions()
        self._init_menu_bar()
        self._init_central_widgets()
        self._init_status_bar()

        self.resize(1200, 800)
        initial_src_lang = "ja"
        if self.current_project is not None:
            initial_src_lang = getattr(self.current_project, "original_language", "ja")
        self.ocr_engine: OcrEngine = OcrEngine(src_lang=initial_src_lang, use_gpu=False)

        self._refresh_settings_cache(refresh_canvas=False)
        self._apply_default_splitter_sizes(force=True)

    # -------------------- init UI --------------------
    def _init_actions(self) -> None:
        self.action_open_folder = QtGui.QAction("Open Folder...", self)
        self.action_open_folder.triggered.connect(self._on_open_folder_triggered)

        self.action_save_project = QtGui.QAction("Save Project", self)
        self.action_save_project.triggered.connect(self._on_save_project_triggered)

        self.action_exit = QtGui.QAction("Exit", self)
        self.action_exit.triggered.connect(self.close)

        self.action_title_settings = QtGui.QAction("Title Settings...", self)
        self.action_title_settings.triggered.connect(self._on_title_settings_triggered)
        self.action_title_settings.setEnabled(False)

        self.action_toggle_overlays = QtGui.QAction("Show translation mask", self)
        self.action_toggle_overlays.setCheckable(True)
        self.action_toggle_overlays.setChecked(self.show_translation_mask)
        self.action_toggle_overlays.triggered.connect(self._on_toggle_overlays_triggered)

        self.action_export_current_page = QtGui.QAction("Export current page", self)
        self.action_export_current_page.triggered.connect(self._on_export_current_page)

        self.action_export_current_page_layered = QtGui.QAction("Export page (OpenRaster)", self)
        self.action_export_current_page_layered.triggered.connect(self._on_export_current_page_layered)

        self.action_export_current_chapter = QtGui.QAction("Export current chapter", self)
        self.action_export_current_chapter.triggered.connect(self._on_export_current_chapter)

        self.action_open_settings = QtGui.QAction("Settings...", self)
        self.action_open_settings.triggered.connect(self._on_open_settings)

        self.action_about = QtGui.QAction("About", self)
        self.action_about.triggered.connect(self._on_about_triggered)

        self.action_toggle_editor = QtGui.QAction("Show block list", self)
        self.action_toggle_editor.setCheckable(True)
        self.action_toggle_editor.setChecked(True)
        self.action_toggle_editor.triggered.connect(self._on_toggle_editor_panel)

    def _init_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        self.menu_file = menu_bar.addMenu("File")
        self.menu_file.addAction(self.action_open_folder)
        self.menu_file.addAction(self.action_save_project)
        self.menu_file.addAction(self.action_export_current_page)
        self.menu_file.addAction(self.action_export_current_page_layered)
        self.menu_file.addAction(self.action_export_current_chapter)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.action_exit)

        self.menu_title = menu_bar.addMenu("Title")
        self.menu_title.addAction(self.action_title_settings)

        self.menu_settings = menu_bar.addMenu("Settings")
        self.menu_settings.addAction(self.action_open_settings)

        self.menu_view = menu_bar.addMenu("View")
        self.menu_view.addAction(self.action_toggle_overlays)
        self.menu_view.addAction(self.action_toggle_editor)
        self.action_reset_layout = QtGui.QAction(tr("action.reset_layout", self._current_language()), self)
        self.action_reset_layout.triggered.connect(self.reset_layout)
        self.menu_view.addAction(self.action_reset_layout)

        self.menu_help = menu_bar.addMenu("Help")
        self.menu_help.addAction(self.action_about)

    def _init_central_widgets(self) -> None:
        self.page_viewer_panel = PageViewerPanel(self)
        self.page_editor = PageEditor(self)
        self.page_editor.retranslateBlocksRequested.connect(
            self._on_retranslate_blocks_requested
        )
        self.page_editor.blockDeleted.connect(self.on_block_deleted)
        self.page_editor.addBlockRequested.connect(self.on_add_block_requested)
        self.page_editor.blockEnabledChanged.connect(self.on_block_enabled_changed)
        self.page_editor.blockTypeChanged.connect(self._on_block_type_changed)
        self.page_editor.currentBlockChanged.connect(self._on_current_block_changed)
        self.page_editor.ocrAndTranslateRequested.connect(self._on_ocr_and_translate_page_triggered)
        self.page_editor.retranslateSelectedRequested.connect(self._on_retranslate_blocks_requested)
        self.page_editor.refreshCanvasRequested.connect(self._on_refresh_translated_canvas)
        self.translated_canvas = TranslatedPageCanvas(self)
        self.layers_panel = LayersPanel(self)
        self.text_properties_panel = TextPropertiesPanel(self)
        self.page_viewer_panel.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.translated_canvas.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding
        )
        self.page_editor.translationChanged.connect(
            self.translated_canvas.update_block_translation
        )
        self.page_editor.blocksChanged.connect(self.mark_current_session_dirty)
        self.translated_canvas.blockAreaSelected.connect(self.on_block_area_selected)
        self.translated_canvas.paintLayerChanged.connect(self.mark_current_session_dirty)
        self.translated_canvas.selectedBubbleChanged.connect(self._on_canvas_selection_changed)
        self.translated_canvas.blockClicked.connect(self.page_editor.select_block_by_id)
        self.translated_canvas.zoomChanged.connect(lambda _: self._update_zoom_slider_from_canvas())
        self.page_viewer_panel.viewer.maskAddRequested.connect(self.on_mask_add_rect)
        self.page_viewer_panel.viewer.maskEraseRequested.connect(self.on_mask_erase_rect)
        self.page_viewer_panel.viewer.showMaskToggled.connect(self._on_viewer_mask_toggled)
        self.page_tools_toolbar = PageToolsToolbar(self)
        self.page_tools_toolbar.maskToggled.connect(self._on_toggle_mask_enabled)
        self.page_tools_toolbar.textToggled.connect(self._on_toggle_text_enabled)
        self.page_tools_toolbar.sfxToggled.connect(self._on_toggle_sfx)
        self.page_tools_toolbar.toolSelected.connect(self._on_tool_selected)
        self.page_tools_toolbar.colorPickRequested.connect(self._on_choose_brush_color)
        self.page_tools_toolbar.zoomInRequested.connect(self._on_zoom_in)
        self.page_tools_toolbar.zoomOutRequested.connect(self._on_zoom_out)
        self.page_tools_toolbar.zoomResetRequested.connect(self._on_zoom_reset)
        self.page_tools_toolbar.zoomFitWidthRequested.connect(self._on_zoom_fit_width)
        self.layers_panel.layerVisibilityChanged.connect(self._on_layer_visibility_changed)
        self.layers_panel.activeLayerChanged.connect(self._on_active_layer_changed)
        self.text_properties_panel.fontChanged.connect(self._on_text_font_changed)
        self.text_properties_panel.sizeChanged.connect(self._on_text_size_changed)
        self.text_properties_panel.alignChanged.connect(self._on_text_align_changed)
        undo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Undo, self)
        redo_shortcut = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Redo, self)
        redo_shortcut_alt = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Y"), self)
        undo_shortcut.activated.connect(self._on_undo)
        redo_shortcut.activated.connect(self._on_redo)
        redo_shortcut_alt.activated.connect(self._on_redo)
        nav_prev = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Left), self)
        nav_next = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_Right), self)
        nav_prev.activated.connect(self._on_go_prev_page)
        nav_next.activated.connect(self._on_go_next_page)
        self._apply_button_hover_styles()

        self.page_viewer_panel.viewActivated.connect(lambda: self._set_active_view("viewer"))
        self.translated_canvas.viewActivated.connect(lambda: self._set_active_view("translated"))

        self.page_editor.setMinimumWidth(220)
        self.page_viewer_panel.setMinimumSize(400, 400)
        self.translated_canvas.setMinimumSize(400, 400)

        viewer_container = QtWidgets.QWidget(self)
        viewer_layout = QtWidgets.QVBoxLayout(viewer_container)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(4)
        viewer_header = QtWidgets.QLabel("Original page", viewer_container)
        viewer_header.setStyleSheet("font-weight: 600;")
        viewer_layout.addWidget(viewer_header)
        viewer_layout.addWidget(self.page_viewer_panel, 1)

        right_panel = QtWidgets.QWidget(self)
        right_layout = QtWidgets.QHBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        translated_container = QtWidgets.QWidget(self)
        translated_layout = QtWidgets.QVBoxLayout(translated_container)
        translated_layout.setContentsMargins(0, 0, 0, 0)
        translated_layout.setSpacing(4)
        translated_header_layout = QtWidgets.QHBoxLayout()
        translated_header_layout.setContentsMargins(0, 0, 0, 0)
        translated_header_layout.setSpacing(8)
        translated_label = QtWidgets.QLabel("Translated page", translated_container)
        translated_label.setStyleSheet("font-weight: 600;")
        self.translated_zoom_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, translated_container)
        self.translated_zoom_slider.setRange(10, 800)
        self.translated_zoom_slider.setSingleStep(5)
        self.translated_zoom_slider.setPageStep(10)
        self.translated_zoom_slider.setValue(100)
        self.translated_zoom_slider.valueChanged.connect(self._on_translated_zoom_changed)
        self.translated_zoom_value = QtWidgets.QLabel("100%", translated_container)
        translated_header_layout.addWidget(translated_label)
        translated_header_layout.addStretch(1)
        translated_header_layout.addWidget(QtWidgets.QLabel("Zoom", translated_container))
        translated_header_layout.addWidget(self.translated_zoom_slider, 1)
        translated_header_layout.addWidget(self.translated_zoom_value)
        translated_layout.addLayout(translated_header_layout)
        translated_layout.addWidget(self.translated_canvas, 1)

        side_panel_layout = QtWidgets.QVBoxLayout()
        side_panel_layout.setContentsMargins(4, 4, 4, 4)
        side_panel_layout.setSpacing(8)
        side_panel_layout.addWidget(self.text_properties_panel)
        side_panel_layout.addWidget(self.layers_panel)
        side_panel_layout.addStretch(1)
        side_container = QtWidgets.QWidget(right_panel)
        side_container.setLayout(side_panel_layout)
        side_container.setFixedWidth(200)
        right_panel.setMinimumSize(400, 400)

        right_layout.addWidget(translated_container, 1)
        right_layout.addWidget(side_container)

        pages_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        pages_splitter.addWidget(viewer_container)
        pages_splitter.addWidget(right_panel)
        pages_splitter.setChildrenCollapsible(False)
        pages_splitter.setHandleWidth(4)
        pages_splitter.setStretchFactor(0, 1)
        pages_splitter.setStretchFactor(1, 2)
        self.pages_splitter = pages_splitter

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.page_editor)
        splitter.addWidget(pages_splitter)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(4)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.main_splitter = splitter
        self._editor_last_size = max(240, self.page_editor.minimumWidth())

        toolbar_container = QtWidgets.QWidget(self)
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(6, 6, 6, 6)
        toolbar_layout.setSpacing(4)
        toolbar_layout.addWidget(self.page_tools_toolbar)
        toolbar_layout.addStretch(1)

        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar_container)
        layout.addWidget(splitter)
        layout.setStretch(0, 0)
        layout.setStretch(1, 1)

        self.setCentralWidget(central)
        self.page_viewer_panel.btn_first.clicked.connect(self._on_go_first_page)
        self.page_viewer_panel.btn_prev.clicked.connect(self._on_go_prev_page)
        self.page_viewer_panel.btn_next.clicked.connect(self._on_go_next_page)
        self.page_viewer_panel.btn_last.clicked.connect(self._on_go_last_page)
        self._set_current_tool(self.current_tool, from_toolbar=False)
        self.layers_panel.set_layer_visible("background", True)
        self.layers_panel.set_layer_visible("mask", True)
        self.layers_panel.set_layer_visible("paint", True)
        self.layers_panel.set_layer_visible("text", True)
        self.layers_panel.set_active_layer("text")
        self._on_active_layer_changed("text")
        self._on_canvas_selection_changed(None)

    def _init_status_bar(self) -> None:
        bar = self.statusBar()
        bar.showMessage(tr("status.ready", self._current_language()))
        self._status_progress_bar = QtWidgets.QProgressBar(self)
        self._status_progress_bar.setRange(0, 0)
        self._status_progress_bar.setFixedWidth(140)
        self._status_progress_bar.setMaximumHeight(14)
        self._status_progress_bar.setVisible(False)

        self._slow_mode_label = QtWidgets.QLabel("", self)
        self._slow_mode_label.setStyleSheet("color: #d18f00; font-weight: 600;")
        self._slow_mode_label.setVisible(False)

        bar.addWidget(self._status_progress_bar)
        bar.addPermanentWidget(self._slow_mode_label)

    # -------------------- helpers --------------------
    def reset_layout(self) -> None:
        """Restore splitter proportions to sane defaults."""
        if hasattr(self, "action_toggle_editor"):
            self.action_toggle_editor.blockSignals(True)
            self.action_toggle_editor.setChecked(True)
            self.action_toggle_editor.blockSignals(False)
        if hasattr(self, "page_editor"):
            self.page_editor.setVisible(True)
        self._apply_default_splitter_sizes(force=True)

    def _default_main_splitter_sizes(self) -> list[int]:
        width = max(self.width(), 1200)
        left = max(260, self.page_editor.minimumWidth() if hasattr(self, "page_editor") else 260)
        right = max(800, width - left)
        return [left, right]

    def _default_pages_splitter_sizes(self) -> list[int]:
        width = max(self.width(), 1200)
        left = max(int(width * 0.42), 380)
        right = max(width - left, 500)
        return [left, right]

    def _splitter_sizes_invalid(self, splitter: Optional[QtWidgets.QSplitter], *, allow_zero_first: bool = False) -> bool:
        if splitter is None:
            return True
        sizes = splitter.sizes()
        if allow_zero_first and sizes:
            sizes = sizes[1:]
        if not sizes:
            return True
        return any(size < 50 for size in sizes)

    def _apply_default_splitter_sizes(self, *, force: bool = False) -> None:
        if not hasattr(self, "main_splitter") or not hasattr(self, "pages_splitter"):
            return
        if force or self._splitter_sizes_invalid(self.main_splitter):
            self.main_splitter.setStretchFactor(0, 0)
            self.main_splitter.setStretchFactor(1, 1)
            self.main_splitter.setSizes(self._default_main_splitter_sizes())
        if force or self._splitter_sizes_invalid(self.pages_splitter):
            self.pages_splitter.setStretchFactor(0, 1)
            self.pages_splitter.setStretchFactor(1, 1)
            self.pages_splitter.setSizes(self._default_pages_splitter_sizes())
        self._layout_initialized = True

    def _set_status_busy(self, busy: bool, message: str | None = None) -> None:
        """Show a small progress bar in the status bar to indicate ongoing work."""
        if message:
            self.statusBar().showMessage(message)
        if hasattr(self, "_status_progress_bar"):
            self._status_progress_bar.setVisible(busy)
            self._status_progress_bar.setRange(0, 0 if busy else 1)
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def _refresh_slow_mode_indicator(self, engine_id: str) -> None:
        """Toggle slow mode badge in the status bar."""
        if not hasattr(self, "_slow_mode_label"):
            return
        if is_slow_mode(engine_id):
            cfg = get_translator_engine_config(engine_id)
            lang = self._current_language()
            name = tr(getattr(cfg, "name_key", cfg.id), lang) if cfg else engine_id
            self._slow_mode_label.setText(f"Slow mode: {name}")
            self._slow_mode_label.setToolTip("Hit rate limit; running in slow mode to keep translating.")
            self._slow_mode_label.setVisible(True)
        else:
            self._slow_mode_label.setVisible(False)

    def _ensure_splitter_integrity(self) -> None:
        editor_hidden = hasattr(self, "action_toggle_editor") and not self.action_toggle_editor.isChecked()
        main_invalid = self._splitter_sizes_invalid(
            getattr(self, "main_splitter", None), allow_zero_first=editor_hidden
        )
        pages_invalid = self._splitter_sizes_invalid(getattr(self, "pages_splitter", None))
        if main_invalid or pages_invalid:
            self._apply_default_splitter_sizes(force=True)
            if editor_hidden:
                self._on_toggle_editor_panel(False)

    def _set_visibility_state(
        self,
        *,
        mask: Optional[bool] = None,
        text: Optional[bool] = None,
        sfx: Optional[bool] = None,
        mark_dirty: bool = True,
    ) -> None:
        """Update visibility toggles across toolbar, viewer, and canvas."""
        session = self.page_sessions.get(self.current_page_index)

        if mask is not None:
            mask_value = bool(mask)
            self.show_translation_mask = mask_value
            self.page_viewer_panel.set_show_translation_mask(mask_value)
            self.translated_canvas.toggle_mask_enabled(mask_value)
            if hasattr(self, "layers_panel"):
                self.layers_panel.set_layer_visible("mask", mask_value)
            if hasattr(self, "page_tools_toolbar"):
                self.page_tools_toolbar.set_visibility_state(mask=mask_value)
            if hasattr(self, "action_toggle_overlays") and self.action_toggle_overlays.isChecked() != mask_value:
                self.action_toggle_overlays.blockSignals(True)
                self.action_toggle_overlays.setChecked(mask_value)
                self.action_toggle_overlays.blockSignals(False)
            if session is not None:
                session.mask_enabled = mask_value
                if mark_dirty:
                    self.mark_current_session_dirty()

        if text is not None:
            text_value = bool(text)
            self.translated_canvas.toggle_text_enabled(text_value)
            if hasattr(self, "layers_panel"):
                self.layers_panel.set_layer_visible("text", text_value)
            if hasattr(self, "page_tools_toolbar"):
                self.page_tools_toolbar.set_visibility_state(text=text_value)
            if session is not None:
                session.text_enabled = text_value
                if mark_dirty:
                    self.mark_current_session_dirty()

        if sfx is not None:
            sfx_value = bool(sfx)
            self.translated_canvas.set_show_sfx(sfx_value)
            if hasattr(self, "page_tools_toolbar"):
                self.page_tools_toolbar.set_visibility_state(sfx=sfx_value)
            if session is not None:
                session.show_sfx = sfx_value
                if mark_dirty:
                    self.mark_current_session_dirty()

    def _set_active_view(self, target: str) -> None:
        if target in ("viewer", "translated"):
            self._active_view = target

    def _on_rate_limit_activated(self, engine_id: str) -> None:
        """Show a non-blocking notice when we switch to slow mode after rate limit."""
        if not consume_slow_mode_notice(engine_id):
            self._refresh_slow_mode_indicator(engine_id)
            return
        cfg = get_translator_engine_config(engine_id)
        lang = self._current_language()
        name = tr(getattr(cfg, "name_key", cfg.id), lang) if cfg else engine_id
        self.statusBar().showMessage(f"{name}: hit rate limit, switched to slow mode.")
        self._refresh_slow_mode_indicator(engine_id)

    def _current_view_target(self) -> Optional[object]:
        return getattr(self, "translated_canvas", None)

    def _apply_zoom_action(self, action: str) -> None:
        canvas = getattr(self, "translated_canvas", None)
        if canvas is None:
            return

        if action == "in" and hasattr(canvas, "zoom_in"):
            canvas.zoom_in()
        elif action == "out" and hasattr(canvas, "zoom_out"):
            canvas.zoom_out()
        elif action == "reset" and hasattr(canvas, "reset_zoom"):
            canvas.reset_zoom()
        elif action == "fit_width" and hasattr(canvas, "zoom_fit_width"):
            canvas.zoom_fit_width()

        self._update_zoom_slider_from_canvas()

    def _update_zoom_slider_from_canvas(self) -> None:
        slider = getattr(self, "translated_zoom_slider", None)
        label = getattr(self, "translated_zoom_value", None)
        canvas = getattr(self, "translated_canvas", None)
        if slider is None or canvas is None:
            return
        try:
            factor = float(canvas.current_zoom_factor())
        except Exception:
            return
        value = int(round(factor * 100))
        clamped = max(slider.minimum(), min(slider.maximum(), value))
        slider.blockSignals(True)
        slider.setValue(clamped)
        slider.blockSignals(False)
        if label is not None:
            label.setText(f"{factor * 100:.0f}%")

    def _on_translated_zoom_changed(self, value: int) -> None:
        canvas = getattr(self, "translated_canvas", None)
        if canvas is None:
            return
        factor = max(0.1, value / 100.0)
        if hasattr(canvas, "set_zoom_factor"):
            canvas.set_zoom_factor(factor)
        label = getattr(self, "translated_zoom_value", None)
        if label is not None:
            label.setText(f"{value}%")

    def _apply_button_hover_styles(self) -> None:
        extra = """
        QPushButton:hover, QToolButton:hover {
            background-color: rgba(80, 150, 255, 0.18);
            border: 1px solid rgba(80, 150, 255, 0.6);
        }
        QPushButton:pressed, QToolButton:pressed {
            background-color: rgba(80, 150, 255, 0.28);
        }
        """
        current = self.styleSheet() or ""
        if extra not in current:
            self.setStyleSheet(current + "\n" + extra)

    def _apply_history_session(self, session: PageSession) -> None:
        """Replace current page session from history snapshot."""
        self._applying_history = True
        try:
            self.page_sessions[self.current_page_index] = session
            self.page_editor.set_page_session(session)
            self.page_viewer_panel.set_blocks(
                [b for b in session.text_blocks if not getattr(b, "deleted", False)]
            )
            self.page_viewer_panel.viewer.set_page_session(session)
            try:
                self.page_viewer_panel.viewer.zoom_fit_window()
            except Exception:
                pass
            pixmap = None
            if session.image_path and Path(session.image_path).is_file():
                pixmap = QtGui.QPixmap(str(session.image_path))
            if pixmap is not None and not pixmap.isNull():
                self.translated_canvas.set_page_session(pixmap, session)
                try:
                    self.translated_canvas.zoom_fit_window()
                except Exception:
                    pass
                self._update_zoom_slider_from_canvas()
            self.current_session_dirty = True
        finally:
            self._applying_history = False

    def _on_undo(self) -> None:
        session = self._history.undo()
        if session is None:
            return
        self._apply_history_session(session)

    def _on_redo(self) -> None:
        session = self._history.redo()
        if session is None:
            return
        self._apply_history_session(session)

    def _set_current_tool(self, tool: PageTool, *, from_toolbar: bool = False) -> None:
        self.current_tool = tool
        if hasattr(self, "page_tools_toolbar") and not from_toolbar:
            self.page_tools_toolbar.set_current_tool(tool)
        if hasattr(self, "page_viewer_panel"):
            self.page_viewer_panel.set_current_tool(tool)
        if hasattr(self, "translated_canvas"):
            self.translated_canvas.set_current_tool(tool)

    def _on_layer_visibility_changed(self, layer: str, visible: bool) -> None:
        if layer == "mask":
            self._set_visibility_state(mask=visible)
        elif layer == "text":
            self._set_visibility_state(text=visible)
        elif layer == "paint":
            self.translated_canvas.set_layer_visible_paint(visible)
        elif layer == "background":
            self.translated_canvas.set_layer_visible_background(visible)

    def _on_active_layer_changed(self, layer: str) -> None:
        mapping = {
            "background": ActiveLayer.BACKGROUND,
            "mask": ActiveLayer.MASK,
            "paint": ActiveLayer.PAINT,
            "text": ActiveLayer.TEXT,
        }
        target = mapping.get(layer)
        if target is None:
            return
        self.translated_canvas.set_active_layer(target)

    def _on_canvas_selection_changed(self, bubble_id: Optional[str]) -> None:
        font_family, font_size, align = self.translated_canvas.selected_bubble_style()
        self.text_properties_panel.setEnabled(bubble_id is not None)
        self.text_properties_panel.set_properties(font_family, font_size, align)
        if bubble_id:
            block_id = self.translated_canvas.first_block_id_for_bubble(bubble_id)
            if block_id:
                self.page_editor.select_block_by_id(block_id)
                self.page_viewer_panel.set_highlighted_block(block_id)
        else:
            self.page_viewer_panel.set_highlighted_block(None)

    def _on_text_font_changed(self, family: Optional[str]) -> None:
        bubble_id = self.translated_canvas.selected_bubble_id
        if not bubble_id:
            return
        self.translated_canvas.apply_bubble_style(bubble_id, font_family=family)
        self.mark_current_session_dirty()

    def _on_text_size_changed(self, size: Optional[int]) -> None:
        bubble_id = self.translated_canvas.selected_bubble_id
        if not bubble_id:
            return
        self.translated_canvas.apply_bubble_style(bubble_id, font_size=size)
        self.mark_current_session_dirty()

    def _on_text_align_changed(self, align: Optional[str]) -> None:
        bubble_id = self.translated_canvas.selected_bubble_id
        if not bubble_id:
            return
        self.translated_canvas.apply_bubble_style(bubble_id, align=align)
        self.mark_current_session_dirty()

    def _on_tool_selected(self, tool: PageTool) -> None:
        self._set_current_tool(tool, from_toolbar=True)

    def _on_zoom_in(self) -> None:
        self._apply_zoom_action("in")

    def _on_zoom_out(self) -> None:
        self._apply_zoom_action("out")

    def _on_zoom_reset(self) -> None:
        self._apply_zoom_action("reset")

    def _on_zoom_fit_width(self) -> None:
        self._apply_zoom_action("fit_width")

    def _get_sessions_dir(self) -> Path:
        """
        Return directory where JSON sessions for the current project are stored.
        Format: <project.folder_path>/.blume/sessions/
        """
        if self.current_project is None:
            raise RuntimeError("Current project is not set")
        return self.current_project.folder_path / SESSIONS_SUBDIR

    def _sync_views_after_session_change(
        self,
        session: PageSession,
        *,
        update_editor: bool = True,
        focus_block_id: Optional[str] = None,
    ) -> None:
        """Refresh left/right views after session changes."""
        visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
        if update_editor:
            self.page_editor.set_page_session(session)
        self.page_viewer_panel.set_blocks(visible_blocks)
        self.page_viewer_panel.viewer.set_page_session(session)
        try:
            self.page_viewer_panel.viewer.zoom_fit_window()
        except Exception:
            pass

        pixmap = getattr(self.translated_canvas, "_current_pixmap", None)
        if pixmap is None and session.image_path:
            pixmap = QtGui.QPixmap(str(session.image_path))
        if pixmap is not None and not pixmap.isNull():
            self.translated_canvas.set_page_session(pixmap, session)
            try:
                self.translated_canvas.zoom_fit_window()
            except Exception:
                pass
            self._update_zoom_slider_from_canvas()
        self.current_session_dirty = False
        self._history.reset(session)
        self.current_session_dirty = False

        if focus_block_id and update_editor:
            try:
                self.page_editor.focus_translation_cell_for_block(focus_block_id)
            except Exception:
                pass

        if self.current_project is not None:
            try:
                page_info = self.current_project.pages[self.current_page_index]
                page_info.ocr_done = bool(visible_blocks)
                page_info.translation_done = any((b.translated_text or "").strip() for b in visible_blocks)
            except Exception:
                pass
        self.current_session_dirty = False

    def mark_current_session_dirty(self) -> None:
        """Mark current page session as needing save."""
        self.current_session_dirty = True
        if self._applying_history:
            return
        session = self.page_sessions.get(self.current_page_index)
        if session is not None:
            self._history.push(session)

    def save_current_session_if_dirty(self) -> None:
        """Persist the current session when there are unsaved changes."""
        if self.current_project is None or not self.current_session_dirty:
            return

        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            return

        sessions_dir = self._get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        paint_image = self.translated_canvas.get_paint_layer_image()
        if paint_image is not None:
            session.paint_layer_image = paint_image
        else:
            session.paint_layer_image = None
        save_page_session(session, sessions_dir)
        session.paint_layer_image = None

        session_path = sessions_dir / f"page_{session.page_index:04d}.json"
        session.session_path = session_path
        try:
            page_info = self.current_project.pages[session.page_index]
            page_info.session_path = session_path
            page_info.ocr_done = bool(session.text_blocks)
            page_info.translation_done = any(
                (b.translated_text or "").strip() for b in session.text_blocks if not getattr(b, "deleted", False)
            )
        except IndexError:
            pass

        self.current_session_dirty = False

    def _apply_settings_snapshot(self, settings: Dict[str, Any], *, refresh_canvas: bool = True) -> None:
        """Apply provided settings dict to runtime state (fonts, theme, language)."""
        self.settings_cache = settings or {}
        fonts_cfg = self.settings_cache.get("fonts", {}) if isinstance(self.settings_cache, dict) else {}
        app_config.ui_font_family = fonts_cfg.get("ui_font_family")
        app_config.manga_font_family = fonts_cfg.get("manga_font_family")
        app_config.sfx_font_family = fonts_cfg.get("sfx_font_family")
        app_instance = QtWidgets.QApplication.instance()
        if app_instance:
            if app_config.ui_font_family:
                app_instance.setFont(QtGui.QFont(app_config.ui_font_family, 9))
            else:
                app_instance.setFont(QtGui.QFont())
        self._apply_theme()
        self._apply_language()
        if refresh_canvas and hasattr(self, "translated_canvas"):
            pixmap = getattr(self.translated_canvas, "_current_pixmap", None)
            session = self.page_sessions.get(self.current_page_index)
            if pixmap is not None and session is not None:
                self.translated_canvas.set_page_session(pixmap, session)

    def _refresh_settings_cache(self, *, refresh_canvas: bool = True) -> None:
        """Reload merged settings for the current project (or global defaults)."""
        project_folder = self.current_project.folder_path if self.current_project else None
        settings = load_effective_settings(project_folder)
        self._apply_settings_snapshot(settings, refresh_canvas=refresh_canvas)

    def _default_resolution_setting(self) -> str:
        if isinstance(self.settings_cache, dict):
            return self.settings_cache.get("general", {}).get("default_resolution_preset", "ask")
        return "ask"

    def _apply_default_resolution_if_needed(self, project: TitleProject) -> None:
        """Apply global default preset when project lacks explicit target size."""
        if getattr(project, "target_width", 0) and getattr(project, "target_height", 0):
            return
        preset_id = self._default_resolution_setting()
        if preset_id == "ask":
            return
        preset = get_preset_by_id(preset_id)
        if preset:
            project.target_width = preset.width
            project.target_height = preset.height
            project.resolution_preset_id = preset.id

    def _maybe_prompt_resolution_choice(self, project: TitleProject) -> None:
        """Show resolution suggestion dialog when scans look unusual or user prefers prompt."""
        stats = compute_resolution_stats(project.pages)
        if not stats.get("count"):
            return
        median_w = stats.get("median_width", 0)
        median_h = stats.get("median_height", 0)
        too_low = median_w < 900 or median_h < 1200
        too_high = median_w > 2800 or median_h > 4200
        missing = not project.target_width or not project.target_height
        ask_every_time = self._default_resolution_setting() == "ask"
        if not (too_low or too_high or missing or ask_every_time):
            return

        dialog = ResolutionSuggestionDialog(stats, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        if dialog.selected_preset_id:
            preset = get_preset_by_id(dialog.selected_preset_id)
            if preset:
                project.target_width = preset.width
                project.target_height = preset.height
                project.resolution_preset_id = preset.id
        elif dialog.keep_original_size:
            if stats.get("median_width") and stats.get("median_height"):
                project.target_width = int(stats["median_width"])
                project.target_height = int(stats["median_height"])
                project.resolution_preset_id = "custom"
        save_project_meta(project)

    def _normalized_path_for_page(self, page_info: PageInfo) -> Path:
        if self.current_project is None:
            return page_info.file_path
        return get_normalized_image_path(self.current_project, page_info)

    def _ensure_session_geometry(
        self, session: PageSession, normalized_path: Path, page_info: PageInfo
    ) -> None:
        """Ensure session bbox coordinates are in the current target resolution."""
        target_size = (
            getattr(self.current_project, "target_width", 0),
            getattr(self.current_project, "target_height", 0),
        )
        if target_size[0] <= 0 or target_size[1] <= 0:
            img_target = QtGui.QImage(str(normalized_path))
            if not img_target.isNull():
                target_size = (img_target.width(), img_target.height())
                if self.current_project is not None:
                    self.current_project.target_width = target_size[0]
                    self.current_project.target_height = target_size[1]
        stored_size = (getattr(session, "page_width", 0), getattr(session, "page_height", 0))
        if target_size[0] and target_size[1] and stored_size == target_size:
            return

        src_size = stored_size
        if src_size == (0, 0):
            img = QtGui.QImage(str(page_info.file_path))
            if not img.isNull():
                src_size = (img.width(), img.height())
        if src_size == (0, 0):
            img = QtGui.QImage(str(normalized_path))
            if not img.isNull():
                src_size = (img.width(), img.height())
        migrate_session_geometry(session, src_size, target_size)

    def _apply_theme(self) -> None:
        """Apply light/dark theme from settings to the application."""
        app_instance = QtWidgets.QApplication.instance()
        if app_instance is None:
            return
        theme = "system"
        if isinstance(self.settings_cache, dict):
            theme = self.settings_cache.get("appearance", {}).get("theme", "system")
        from main import apply_theme

        apply_theme(app_instance, theme)

    def _current_language(self) -> str:
        """Return current UI language code (default: en)."""
        if isinstance(self.settings_cache, dict):
            lang = self.settings_cache.get("general", {}).get("ui_language", "en")
            return (lang or "en").lower()
        return "en"

    def _generate_block_id(self) -> str:
        """Generate a unique block id for the current project."""
        existing_ids = {b.id for sess in self.page_sessions.values() for b in sess.text_blocks}
        while True:
            candidate = f"b{uuid.uuid4().hex[:8]}"
            if candidate not in existing_ids:
                return candidate

    def _apply_language(self) -> None:
        """Apply translated labels to menus and actions."""
        lang = self._current_language()

        if hasattr(self, "action_open_folder"):
            self.action_open_folder.setText(tr("action.open_folder", lang))
            self.action_save_project.setText(tr("action.save_project", lang))
            self.action_export_current_page.setText(tr("action.export_page", lang))
            self.action_export_current_page_layered.setText(tr("action.export_page_layered", lang))
            self.action_export_current_chapter.setText(tr("action.export_chapter", lang))
            self.action_exit.setText(tr("action.exit", lang))
            self.action_title_settings.setText(tr("action.title_settings", lang))
            self.action_toggle_overlays.setText(tr("action.show_overlays", lang))
            self.action_open_settings.setText(tr("settings.title", lang))
            self.action_about.setText(tr("action.about", lang))
            self.action_toggle_editor.setText(tr("action.toggle_editor", lang))

        if hasattr(self, "menu_file"):
            self.menu_file.setTitle(tr("menu.file", lang))
            self.menu_title.setTitle(tr("menu.title", lang))
            self.menu_settings.setTitle(tr("menu.settings", lang))
            self.menu_view.setTitle(tr("menu.view", lang))
            self.menu_help.setTitle(tr("menu.help", lang))

        if hasattr(self, "page_viewer_panel") and hasattr(self.page_viewer_panel.viewer, "ocr_button"):
            self.page_viewer_panel.viewer.ocr_button.setText(tr("action.ocr_translate", lang))
        if hasattr(self, "page_editor") and hasattr(self.page_editor, "set_language"):
            try:
                self.page_editor.set_language(lang)
            except Exception:
                pass
        if hasattr(self, "page_tools_toolbar"):
            try:
                self.page_tools_toolbar.set_language(lang)
            except Exception:
                pass

    def _resolve_ocr_engine(self) -> Optional[tuple[str, EngineConfig | None, Dict[str, Any]]]:
        """Return selected OCR engine id/config/state or None if unavailable."""
        lang = self._current_language()
        self._refresh_settings_cache(refresh_canvas=False)
        ocr_settings = self.settings_cache.get("ocr", {}) if isinstance(self.settings_cache, dict) else {}
        selected_ocr_raw = ocr_settings.get("selected", "")
        selected_ocr_id = normalize_engine_id(selected_ocr_raw)
        if not selected_ocr_id:
            if not self._open_settings_dialog("OCR"):
                QtWidgets.QMessageBox.information(
                    self, tr("msg.error", lang), tr("msg.ocr_not_configured", lang)
                )
                return None
            ocr_settings = self.settings_cache.get("ocr", {}) if isinstance(self.settings_cache, dict) else {}
            selected_ocr_id = normalize_engine_id(ocr_settings.get("selected", ""))
        if not selected_ocr_id:
            return None

        ocr_config: EngineConfig | None = ENGINE_BY_ID.get(selected_ocr_id)
        if ocr_config is None:
            QtWidgets.QMessageBox.warning(
                self, tr("msg.error", lang), "Selected OCR engine is not available."
            )
            return None
        ocr_state: Dict[str, Any] = {}
        engines_state = ocr_settings.get("engines", {}) if isinstance(ocr_settings, dict) else {}
        if isinstance(engines_state, dict):
            ocr_state = engines_state.get(selected_ocr_id, engines_state.get(selected_ocr_raw, {}))

        if ocr_config is not None:
            engine_name = tr(getattr(ocr_config, "name_key", ocr_config.id), lang)
            if ocr_config.mode == "offline" and not ocr_state.get("downloaded"):
                QtWidgets.QMessageBox.information(
                    self,
                    tr("msg.error", lang),
                    f"{engine_name}: {tr('settings.status.not_downloaded', lang)}",
                )
                self.statusBar().showMessage(f"{engine_name} models are not downloaded yet.")
                return None
            if ocr_config.requires_api_key:
                api_key = str(ocr_state.get("api_key", "")).strip()
                endpoint = str(ocr_state.get("endpoint", "")).strip()
                if not api_key or (ocr_config.requires_endpoint and not endpoint):
                    QtWidgets.QMessageBox.warning(
                        self,
                        tr("msg.error", lang),
                        tr("error.enter_api_key", lang),
                    )
                    return None

        return selected_ocr_id, ocr_config, ocr_state

    def _resolve_translator_engine(self) -> Optional[tuple[str, EngineConfig | None, Dict[str, Any]]]:
        """Return selected translator id/config/state or None if unavailable."""
        lang = self._current_language()
        self._refresh_settings_cache()
        translator_settings = (
            self.settings_cache.get("translator", {}) if isinstance(self.settings_cache, dict) else {}
        )
        selected_translator_raw = translator_settings.get("selected", "")
        selected_translator = normalize_translator_id(selected_translator_raw)
        if not selected_translator:
            if not self._open_settings_dialog("translator"):
                QtWidgets.QMessageBox.information(
                    self, tr("msg.error", lang), tr("msg.translator_not_configured", lang)
                )
                return None
            translator_settings = (
                self.settings_cache.get("translator", {}) if isinstance(self.settings_cache, dict) else {}
            )
            selected_translator = normalize_translator_id(translator_settings.get("selected", ""))
        if not selected_translator:
            return None

        translator_config: EngineConfig | None = get_translator_engine_config(selected_translator)
        if translator_config is None:
            QtWidgets.QMessageBox.warning(
                self, tr("msg.error", lang), "Selected translator engine is not available."
            )
            return None
        translator_state: Dict[str, Any] = {}
        translator_engines_state = (
            translator_settings.get("engines", {}) if isinstance(translator_settings, dict) else {}
        )
        if isinstance(translator_engines_state, dict):
            translator_state = translator_engines_state.get(
                selected_translator, translator_engines_state.get(selected_translator_raw, {})
            )
        if translator_config is not None:
            engine_name = tr(getattr(translator_config, "name_key", translator_config.id), lang)
            if translator_config.mode == "offline" and not translator_state.get("downloaded"):
                QtWidgets.QMessageBox.information(
                    self,
                    tr("msg.error", lang),
                    f"{engine_name}: {tr('settings.status.not_downloaded', lang)}",
                )
                self.statusBar().showMessage(f"{engine_name} models are not downloaded yet.")
                return None
            api_optional = getattr(translator_config, "api_optional", False)
            use_api = bool(translator_state.get("use_api", False)) if api_optional else True
            if translator_config.requires_api_key and (use_api or not api_optional):
                api_key = str(translator_state.get("api_key", "")).strip()
                endpoint = str(translator_state.get("endpoint", "")).strip()
                if not api_key or (translator_config.requires_endpoint and not endpoint):
                    QtWidgets.QMessageBox.warning(
                        self,
                        tr("msg.error", lang),
                        tr("error.enter_api_key", lang),
                    )
                    return None

        return selected_translator, translator_config, translator_state

    def _run_ocr_and_translate_for_block(self, block_id: str, rect: QtCore.QRectF) -> None:
        """Run OCR+translation for a manually added block and refresh views."""
        session = self.page_sessions.get(self.current_page_index)
        project = self.current_project
        if session is None or project is None:
            return

        target_block = session.get_block_by_id(block_id) if hasattr(session, "get_block_by_id") else None
        if target_block is None:
            return

        ocr_info = self._resolve_ocr_engine()
        translator_info = self._resolve_translator_engine()
        if ocr_info is None or translator_info is None:
            return
        _ocr_id, _ocr_config, _ocr_state = ocr_info
        translator_id, _translator_config, translator_state = translator_info

        page_info = project.pages[self.current_page_index] if project.pages else None
        image_path = session.image_path or (page_info.normalized_path if page_info else None)
        if image_path is None and page_info is not None:
            image_path = self._normalized_path_for_page(page_info)
        if image_path is None:
            return

        try:
            image_np = load_image_as_np(image_path)
        except Exception:
            QtWidgets.QMessageBox.critical(
                self, tr("msg.error", self._current_language()), "Failed to load page image for OCR."
            )
            return

        height, width = image_np.shape[:2]
        x1 = max(0, int(rect.left()))
        y1 = max(0, int(rect.top()))
        x2 = min(width, int(rect.right()))
        y2 = min(height, int(rect.bottom()))
        if x2 <= x1 or y2 <= y1:
            return

        cropped = image_np[y1:y2, x1:x2]
        try:
            ocr_blocks = self.ocr_engine.recognize(cropped, src_lang=project.original_language)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self,
                tr("msg.error", self._current_language()),
                f"Failed to run OCR on selection: {exc}",
            )
            return

        adjusted_bboxes: list[tuple[int, int, int, int]] = []
        texts: list[str] = []
        confidences: list[float] = []
        for ob in ocr_blocks:
            ax1 = x1 + int(ob.bbox[0])
            ay1 = y1 + int(ob.bbox[1])
            ax2 = x1 + int(ob.bbox[2])
            ay2 = y1 + int(ob.bbox[3])
            adjusted_bboxes.append((ax1, ay1, ax2, ay2))
            texts.append(ob.text or "")
            confidences.append(float(ob.confidence))

        if adjusted_bboxes:
            min_x = min(b[0] for b in adjusted_bboxes)
            min_y = min(b[1] for b in adjusted_bboxes)
            max_x = max(b[2] for b in adjusted_bboxes)
            max_y = max(b[3] for b in adjusted_bboxes)
            target_block.bbox = (min_x, min_y, max(max_x, min_x + 1), max(max_y, min_y + 1))
        else:
            target_block.bbox = (
                x1,
                y1,
                max(x2, x1 + 1),
                max(y2, y1 + 1),
            )

        combined_text = "\n".join(t.strip() for t in texts if t and t.strip()).strip()
        target_block.original_text = combined_text
        target_block.translated_text = ""
        target_block.enabled = True
        target_block.manual = True
        if confidences:
            target_block.confidence = max(confidences)
        if combined_text:
            target_block.block_type = infer_block_type(combined_text)
            target_block.orientation = infer_orientation(target_block.bbox, combined_text)

        if combined_text:
            try:
                self.translation_service.translate_blocks(
                    blocks=[target_block],
                    project=project,
                    engine_id=translator_id,
                    engine_state=translator_state,
                    src_lang=project.original_language,
                    dst_lang=project.target_language,
                )
            except Exception as exc:  # noqa: BLE001
                QtWidgets.QMessageBox.critical(
                    self,
                    tr("msg.translation_error", self._current_language()),
                    f"Failed to translate selection: {exc}",
                )

        self._sync_views_after_session_change(session, update_editor=True, focus_block_id=target_block.id)
        self.mark_current_session_dirty()

    def _on_choose_brush_color(self) -> None:
        """Open color dialog and set brush color for translated canvas."""
        color = QtWidgets.QColorDialog.getColor(
            self.translated_canvas.brush_color(), self, "Выбор цвета кисти"
        )
        if color.isValid():
            self.translated_canvas.set_brush_color(color)

    def _set_blocks_enabled_in_rect(self, rect: QtCore.QRectF, enabled: bool) -> bool:
        """Update enabled flag for all blocks intersecting the given rect.

        Returns True if at least one block intersects the rect (even if state was unchanged).
        """
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            return False

        changed = False
        intersected = False
        for block in session.text_blocks:
            if getattr(block, "deleted", False):
                continue
            x1, y1, x2, y2 = block.bbox
            w = max(1, x2 - x1)
            h = max(1, y2 - y1)
            block_rect = QtCore.QRectF(float(x1), float(y1), float(w), float(h))
            if not block_rect.intersects(rect):
                continue

            intersected = True
            if block.enabled != enabled:
                block.enabled = enabled
                changed = True

        if changed:
            self._sync_views_after_session_change(session, update_editor=True)
            self.mark_current_session_dirty()

        return intersected

    def _create_manual_block(self, rect: QtCore.QRectF, focus_editor: bool = True) -> Optional[str]:
        """Create a manual block from the given rect and refresh views."""
        if rect.width() <= 1 or rect.height() <= 1:
            return None
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            return None

        new_id = self._generate_block_id()
        bbox = (
            int(rect.x()),
            int(rect.y()),
            int(rect.x() + rect.width()),
            int(rect.y() + rect.height()),
        )

        new_block = TextBlock(
            id=new_id,
            bbox=bbox,
            original_text="",
            translated_text="",
            block_type="dialog",
            enabled=True,
            orientation="horizontal",
            confidence=1.0,
            deleted=False,
            manual=True,
            font_size=None,
        )

        session.text_blocks.append(new_block)
        self.mark_current_session_dirty()
        if self.current_project is not None:
            try:
                page_info = self.current_project.pages[self.current_page_index]
                page_info.ocr_done = True
            except Exception:
                pass

        self._sync_views_after_session_change(
            session, update_editor=True, focus_block_id=new_id if focus_editor else None
        )
        return new_id

    @QtCore.Slot()
    def on_add_block_requested(self) -> None:
        """Switch canvas to rectangle selection mode for a new block."""
        self.translated_canvas.set_add_block_mode(True)

    @QtCore.Slot(QtCore.QRectF)
    def on_block_area_selected(self, rect: QtCore.QRectF) -> None:
        """Create a new manual TextBlock from the selected area."""
        self._create_manual_block(rect, focus_editor=True)

    @QtCore.Slot(QtCore.QRectF)
    def on_mask_add_rect(self, rect: QtCore.QRectF) -> None:
        """Handle mask brush selection on the left viewer."""
        intersected = self._set_blocks_enabled_in_rect(rect, enabled=True)
        if intersected:
            return
        new_block_id = self._create_manual_block(rect, focus_editor=True)
        if new_block_id:
            self._run_ocr_and_translate_for_block(new_block_id, rect)

    @QtCore.Slot(QtCore.QRectF)
    def on_mask_erase_rect(self, rect: QtCore.QRectF) -> None:
        """Handle mask eraser selection on the left viewer."""
        self._set_blocks_enabled_in_rect(rect, enabled=False)

    @QtCore.Slot(str, bool)
    def on_block_enabled_changed(self, block_id: str, enabled: bool) -> None:
        """Sync enabled flag changes from the table to canvases."""
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            return

        for block in session.text_blocks:
            if block.id == block_id:
                if block.enabled == enabled:
                    return
                block.enabled = enabled
                break
        else:
            return

        self._sync_views_after_session_change(session, update_editor=False)
        self.mark_current_session_dirty()

    def _on_block_type_changed(self, block_id: str, block_type: str) -> None:
        """Update block type and refresh overlays."""
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            return
        target = session.get_block_by_id(block_id) if hasattr(session, "get_block_by_id") else None
        if target is None:
            return
        if target.block_type == block_type:
            return
        target.block_type = block_type
        self._sync_views_after_session_change(session, update_editor=False)
        self.mark_current_session_dirty()

    def _on_current_block_changed(self, block_id: str) -> None:
        """Highlight current block on both viewers."""
        if hasattr(self, "page_viewer_panel"):
            self.page_viewer_panel.set_highlighted_block(block_id)
        if hasattr(self, "translated_canvas"):
            self.translated_canvas.set_highlighted_block(block_id)

    def _on_refresh_translated_canvas(self) -> None:
        """Force re-render of the translated canvas from the current session."""
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            return
        page_info = None
        if self.current_project and 0 <= self.current_page_index < len(self.current_project.pages):
            page_info = self.current_project.pages[self.current_page_index]
        pixmap_path = session.image_path or (page_info.normalized_path if page_info else None)
        if pixmap_path is None and page_info is not None:
            pixmap_path = page_info.file_path
        if pixmap_path is None:
            return
        pixmap = QtGui.QPixmap(str(pixmap_path))
        if not pixmap.isNull():
            self.translated_canvas.set_page_session(pixmap, session)

    def _on_viewer_mask_toggled(self, checked: bool) -> None:
        """Keep menu action in sync with viewer mask checkbox."""
        self.show_translation_mask = bool(checked)
        if hasattr(self, "page_tools_toolbar"):
            self.page_tools_toolbar.set_visibility_state(mask=self.show_translation_mask)
        if hasattr(self, "layers_panel"):
            self.layers_panel.set_layer_visible("mask", self.show_translation_mask)
        if hasattr(self, "action_toggle_overlays") and self.action_toggle_overlays.isChecked() != self.show_translation_mask:
            self.action_toggle_overlays.blockSignals(True)
            self.action_toggle_overlays.setChecked(self.show_translation_mask)
            self.action_toggle_overlays.blockSignals(False)
        session = self.page_sessions.get(self.current_page_index)
        if session is not None:
            if session.mask_enabled != self.show_translation_mask:
                session.mask_enabled = self.show_translation_mask
                self.mark_current_session_dirty()

    @QtCore.Slot(str)
    def on_block_deleted(self, block_id: str) -> None:
        """Handle block deletion from the editor."""
        session = self.page_sessions.get(self.current_page_index)
        if session is not None:
            for block in session.text_blocks:
                if block.id == block_id:
                    block.deleted = True
            visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
            self.page_viewer_panel.set_blocks(visible_blocks)
            self.page_viewer_panel.viewer.set_page_session(session)
            try:
                self.page_viewer_panel.viewer.zoom_fit_window()
            except Exception:
                pass
            self.page_editor.set_page_session(session)
            if self.current_project is not None:
                try:
                    page_info = self.current_project.pages[self.current_page_index]
                    page_info.ocr_done = bool(visible_blocks)
                    page_info.translation_done = any((b.translated_text or "").strip() for b in visible_blocks)
                except Exception:
                    pass
            self.mark_current_session_dirty()

        self.translated_canvas.remove_block(block_id)

    def _on_toggle_mask_enabled(self, checked: bool) -> None:
        self._set_visibility_state(mask=checked)

    def _on_toggle_text_enabled(self, checked: bool) -> None:
        self._set_visibility_state(text=checked)

    def _on_toggle_sfx(self, checked: bool) -> None:
        self._set_visibility_state(sfx=checked)

    def _open_settings_dialog(self, tab: Optional[str] = None) -> bool:
        """Open the global settings dialog, optionally focusing a tab."""
        old_settings = dict(self.settings_cache) if isinstance(self.settings_cache, dict) else {}
        lang = "en"
        if isinstance(self.settings_cache, dict):
            lang = self.settings_cache.get("general", {}).get("ui_language", "en")
        dialog = SettingsDialog(
            project_folder=self.current_project.folder_path if self.current_project else None,
            parent=self,
            language=lang,
        )
        dialog.settingsApplied.connect(self._apply_settings_snapshot)
        if tab:
            dialog.open_tab(tab)
        result = dialog.exec()
        updated_settings = dialog.get_updated_settings()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            self._apply_settings_snapshot(updated_settings)
            return True
        if updated_settings and updated_settings != old_settings:
            self._apply_settings_snapshot(updated_settings)
            return True
        return False

    def _load_sessions_for_current_project(self) -> None:
        """Load saved sessions (if any) for the current project."""
        if self.current_project is None:
            return

        self.page_sessions.clear()
        self.current_session_dirty = False
        sessions_dir = self._get_sessions_dir()
        if not sessions_dir.is_dir():
            return

        for page_info in self.current_project.pages:
            idx = page_info.index
            normalized_path = self._normalized_path_for_page(page_info)
            page_info.normalized_path = normalized_path
            session_path = sessions_dir / f"page_{idx:04d}.json"
            if not session_path.is_file():
                continue
            try:
                session = load_page_session(sessions_dir, idx)
            except Exception:
                continue
            session.project_id = self.current_project.title_id
            session.page_index = idx
            session.image_path = normalized_path
            session.session_path = session_path
            session.original_image_path = page_info.file_path
            self._ensure_session_geometry(session, normalized_path, page_info)
            session.page_width = getattr(self.current_project, "target_width", 0)
            session.page_height = getattr(self.current_project, "target_height", 0)
            self.page_sessions[idx] = session

            page_info.session_path = session_path
            visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
            page_info.ocr_done = bool(visible_blocks)
            page_info.translation_done = any((b.translated_text or "").strip() for b in visible_blocks)
        self.current_session_dirty = False

    def _sync_current_editor_to_session(self) -> None:
        """Sync PageEditor data into current PageSession (if exists) and mark as dirty."""
        if self.current_project is None:
            return
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            return
        visible_blocks = self.page_editor.get_blocks()
        deleted_blocks = [b for b in session.text_blocks if getattr(b, "deleted", False)]
        session.text_blocks = deleted_blocks + visible_blocks

        page_info = self.current_project.pages[self.current_page_index]
        page_info.translation_done = any((b.translated_text or "").strip() for b in visible_blocks)
        page_info.ocr_done = bool(session.text_blocks)
        self.mark_current_session_dirty()

    def _save_current_page_session_if_needed(self) -> None:
        """Save current page session if it was marked dirty (compat wrapper)."""
        self.save_current_session_if_dirty()

    # -------------------- actions --------------------
    def _on_open_folder_triggered(self) -> None:
        dialog = QtWidgets.QFileDialog(self)
        dialog.setFileMode(QtWidgets.QFileDialog.FileMode.Directory)
        dialog.setOption(QtWidgets.QFileDialog.Option.ShowDirsOnly, True)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        selected = dialog.selectedFiles()
        if not selected:
            return
        folder_path = Path(selected[0])
        try:
            project = open_project_from_folder(folder_path)
            self.current_project = project
            self.current_page_index = 0
            self.page_sessions.clear()
            self.context_manager.clear()
            project.context_manager = self.context_manager
            self.current_session_dirty = False
            self._refresh_settings_cache()
            self._apply_default_resolution_if_needed(project)
            self._maybe_prompt_resolution_choice(project)
            save_project_meta(project)
            self._load_sessions_for_current_project()
            self._load_current_page()
            self._update_navigation_bar()
            self.action_title_settings.setEnabled(True)
            self.statusBar().showMessage(
                tr("status.project_opened", self._current_language()).format(name=project.title_name)
            )
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Error", str(exc))

    def _on_save_project_triggered(self) -> None:
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self, tr("msg.no_project_title", lang), tr("msg.no_project", lang)
            )
            return

        self._sync_current_editor_to_session()
        self.save_current_session_if_dirty()

        sessions_dir = self._get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        for session in self.page_sessions.values():
            save_page_session(session, sessions_dir)
            session.session_path = sessions_dir / f"page_{session.page_index:04d}.json"

            try:
                page_info = self.current_project.pages[session.page_index]
                page_info.session_path = session.session_path
            except IndexError:
                continue

        self.current_session_dirty = False
        self.statusBar().showMessage(tr("status.project_saved", lang))

    def _on_title_settings_triggered(self) -> None:
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self, tr("msg.no_project_title", lang), tr("msg.no_project", lang)
            )
            return
        dlg = TitleSettingsDialog(self.current_project, parent=self, language=lang)
        result = dlg.exec()
        if result == QtWidgets.QDialog.DialogCode.Accepted:
            save_project_meta(self.current_project)
            self._on_title_settings_applied()
            self.statusBar().showMessage(tr("title.settings", lang))

    def _on_open_ocr_settings(self) -> None:
        """Open OCR settings tab inside the unified settings dialog."""
        if self._open_settings_dialog("OCR"):
            self.statusBar().showMessage(tr("status.settings_saved", self._current_language()))

    def _on_open_settings(self) -> None:
        """Open unified settings dialog (general tab by default)."""
        if self._open_settings_dialog():
            self.statusBar().showMessage(tr("status.settings_saved", self._current_language()))

    def _on_export_current_page(self) -> None:
        """
        Export the current page image with translated text into <chapter>/<target_lang>/.
        """
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_project_title", lang),
                tr("msg.no_project", lang),
            )
            return

        self._sync_current_editor_to_session()
        self.save_current_session_if_dirty()
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_data", lang),
                tr("msg.no_session", lang),
            )
            return

        dst_lang = self.current_project.target_language or "ru"
        try:
            output_path = export_page_with_translations(
                session,
                dst_lang=dst_lang,
                content_type=self.current_project.content_type,
                color_mode=self.current_project.color_mode,
            )
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self,
                tr("msg.export_title", lang),
                f"{tr('msg.export_error', lang)}\n{exc}",
            )
            return

        QtWidgets.QMessageBox.information(
            self,
            tr("msg.export_title", lang),
            f"{tr('msg.export_done', lang)}\n{output_path}",
        )

    def _on_export_current_page_layered(self) -> None:
        """Export current page as layered OpenRaster (.ora)."""
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_project_title", lang),
                tr("msg.no_project", lang),
            )
            return

        self._sync_current_editor_to_session()
        self.save_current_session_if_dirty()
        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_data", lang),
                tr("msg.no_session", lang),
            )
            return

        default_name = f"page_{session.page_index:04d}.ora"
        dialog_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            tr("action.export_page_layered", lang),
            str(self.current_project.folder_path / default_name),
            "OpenRaster (*.ora)",
        )
        if not dialog_path:
            return

        try:
            export_data = build_export_page_data(session)
            export_page_to_openraster(export_data, Path(dialog_path))
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self,
                tr("msg.export_title", lang),
                f"{tr('msg.export_error', lang)}\n{exc}",
            )
            return

        QtWidgets.QMessageBox.information(
            self,
            tr("msg.export_title", lang),
            f"{tr('msg.export_done', lang)}\n{dialog_path}",
        )

    def _on_export_current_chapter(self) -> None:
        """Export the chapter containing the current page."""
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_project_title", lang),
                tr("msg.no_project", lang),
            )
            return

        if not self.current_project.pages:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_data", lang),
                tr("msg.no_pages", lang),
            )
            return

        page_info = self.current_project.pages[self.current_page_index]
        chapter_number = page_info.chapter_number

        self._sync_current_editor_to_session()
        self.save_current_session_if_dirty()

        self._export_chapter(chapter_number)

    def _on_ocr_and_translate_page_triggered(self) -> None:
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self, tr("msg.no_project_title", lang), tr("msg.no_project", lang)
            )
            return

        project = self.current_project
        pages = project.pages
        if not pages:
            QtWidgets.QMessageBox.information(self, tr("msg.no_data", lang), tr("msg.no_pages", lang))
            return
        if not (0 <= self.current_page_index < len(pages)):
            QtWidgets.QMessageBox.critical(self, tr("msg.error", lang), tr("msg.invalid_index", lang))
            return

        page_info: PageInfo = pages[self.current_page_index]
        image_path = page_info.normalized_path or self._normalized_path_for_page(page_info)
        page_info.normalized_path = image_path

        project_cfg_path = project.meta_path or (project.folder_path / "project.yaml")
        self._refresh_settings_cache()

        ocr_settings = self.settings_cache.get("ocr", {}) if isinstance(self.settings_cache, dict) else {}
        translator_settings = (
            self.settings_cache.get("translator", {}) if isinstance(self.settings_cache, dict) else {}
        )

        selected_ocr_raw = ocr_settings.get("selected", "")
        selected_ocr_id = normalize_engine_id(selected_ocr_raw)
        if not selected_ocr_id:
            if not self._open_settings_dialog("OCR"):
                QtWidgets.QMessageBox.information(
                    self, tr("msg.error", lang), tr("msg.ocr_not_configured", lang)
                )
                return
            ocr_settings = self.settings_cache.get("ocr", {})
            selected_ocr_id = normalize_engine_id(ocr_settings.get("selected", ""))

        selected_translator_raw = translator_settings.get("selected", "")
        selected_translator_id = normalize_translator_id(selected_translator_raw)
        if not selected_translator_id:
            if not self._open_settings_dialog("translator"):
                QtWidgets.QMessageBox.information(
                    self, tr("msg.error", lang), tr("msg.translator_not_configured", lang)
                )
                return
            translator_settings = (
                self.settings_cache.get("translator", {}) if isinstance(self.settings_cache, dict) else {}
            )
            selected_translator_id = normalize_translator_id(translator_settings.get("selected", ""))

        ocr_config: EngineConfig | None = ENGINE_BY_ID.get(selected_ocr_id)
        translator_config: EngineConfig | None = get_translator_engine_config(selected_translator_id)

        ocr_state: Dict[str, Any] = {}
        engines_state = ocr_settings.get("engines", {}) if isinstance(ocr_settings, dict) else {}
        if isinstance(engines_state, dict):
            ocr_state = engines_state.get(selected_ocr_id, engines_state.get(selected_ocr_raw, {}))

        translator_state: Dict[str, Any] = {}
        translator_engines_state = (
            translator_settings.get("engines", {}) if isinstance(translator_settings, dict) else {}
        )
        if isinstance(translator_engines_state, dict):
            translator_state = translator_engines_state.get(
                selected_translator_id, translator_engines_state.get(selected_translator_raw, {})
            )

        if ocr_config is not None:
            ocr_name = tr(getattr(ocr_config, "name_key", ocr_config.id), lang)
            if ocr_config.mode == "offline" and not ocr_state.get("downloaded"):
                QtWidgets.QMessageBox.information(
                    self,
                    tr("msg.error", lang),
                    f"{ocr_name}: {tr('settings.status.not_downloaded', lang)}",
                )
                self.statusBar().showMessage(f"{ocr_name} models are not downloaded yet.")
                return
            if ocr_config.requires_api_key:
                api_key = str(ocr_state.get("api_key", "")).strip()
                endpoint = str(ocr_state.get("endpoint", "")).strip()
                if not api_key or (ocr_config.requires_endpoint and not endpoint):
                    QtWidgets.QMessageBox.warning(
                        self,
                        tr("msg.error", lang),
                        tr("error.enter_api_key", lang),
                    )
                    return

        if translator_config is not None:
            translator_name = tr(getattr(translator_config, "name_key", translator_config.id), lang)
            if translator_config.mode == "offline" and not translator_state.get("downloaded"):
                QtWidgets.QMessageBox.information(
                    self,
                    tr("msg.error", lang),
                    f"{translator_name}: {tr('settings.status.not_downloaded', lang)}",
                )
                self.statusBar().showMessage(f"{translator_name} models are not downloaded yet.")
                return
            api_optional = getattr(translator_config, "api_optional", False)
            use_api = bool(translator_state.get("use_api", False)) if api_optional else True
            if translator_config.requires_api_key and (use_api or not api_optional):
                api_key = str(translator_state.get("api_key", "")).strip()
                endpoint = str(translator_state.get("endpoint", "")).strip()
                if not api_key or (translator_config.requires_endpoint and not endpoint):
                    QtWidgets.QMessageBox.warning(
                        self,
                        tr("msg.error", lang),
                        tr("error.enter_api_key", lang),
                    )
                    return

        # Ensure metadata exists; create/save defaults if missing
        if project.meta_path is None:
            save_project_meta(project)
            project.meta_path = project_cfg_path
            TitleSettingsDialog(self.current_project, parent=self, language=lang).exec()

        try:
            self._refresh_slow_mode_indicator(selected_translator_id)
            self._set_status_busy(True, "Processing page...")
            self.page_viewer_panel.set_progress("OCR + translate…", True)
            image = load_image_as_np(image_path)
            src_lang = project.original_language
            dst_lang = project.target_language

            ocr_blocks = self.ocr_engine.recognize(image, src_lang=src_lang)
            text_blocks = ocr_blocks_to_text_blocks(
                ocr_blocks, skip_sfx_by_default=getattr(project, "skip_sfx_by_default", True)
            )
            text_blocks = self.translation_service.translate_blocks(
                blocks=text_blocks,
                project=project,
                engine_id=selected_translator_id,
                engine_state=translator_state,
                src_lang=src_lang,
                dst_lang=dst_lang,
            )

            session = PageSession(
                project_id=project.title_id,
                page_index=self.current_page_index,
                image_path=image_path,
                original_image_path=page_info.file_path,
                text_blocks=text_blocks,
                src_lang=src_lang,
                dst_lang=dst_lang,
                page_width=getattr(project, "target_width", image.shape[1]),
                page_height=getattr(project, "target_height", image.shape[0]),
                session_path=None,
            )

            self.page_sessions[self.current_page_index] = session
            self.page_editor.set_page_session(session)
            self.page_viewer_panel.set_blocks(text_blocks)
            self.page_viewer_panel.viewer.set_page_session(session)
            try:
                self.page_viewer_panel.viewer.zoom_fit_window()
            except Exception:
                pass
            pixmap = QtGui.QPixmap(str(image_path))
            if not pixmap.isNull():
                self.translated_canvas.set_page_session(pixmap, session)
                self._update_zoom_slider_from_canvas()
            page_info.ocr_done = True
            page_info.translation_done = True
            self.mark_current_session_dirty()

            self.statusBar().showMessage(
                tr("status.ocr_done", lang).format(
                    page=self.current_page_index + 1, blocks=len(text_blocks)
                )
            )
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, tr("msg.ocr_translation_error", lang), str(exc))
            self.statusBar().showMessage(tr("msg.ocr_translation_error", lang))
        finally:
            self.page_viewer_panel.set_progress("", False)
            self._set_status_busy(False)

    def _on_about_triggered(self) -> None:
        lang = self._current_language()
        QtWidgets.QMessageBox.information(self, tr("title.about", lang), tr("msg.about_text", lang).format(app=APP_NAME))

    def _on_toggle_overlays_triggered(self, checked: bool) -> None:
        self._set_visibility_state(mask=checked)

    def _on_toggle_editor_panel(self, checked: bool) -> None:
        if not hasattr(self, "main_splitter"):
            return
        if not checked:
            sizes = self.main_splitter.sizes()
            if sizes:
                self._editor_last_size = max(self._editor_last_size, sizes[0], self.page_editor.minimumWidth())
            self.page_editor.setVisible(False)
            remaining = max(1, sizes[1] if len(sizes) > 1 else self.width())
            self.main_splitter.setSizes([0, remaining])
        else:
            self.page_editor.setVisible(True)
            sizes = self.main_splitter.sizes()
            right = sizes[1] if len(sizes) > 1 else max(800, self.width())
            left = max(self._editor_last_size or 200, self.page_editor.minimumWidth(), 220)
            self.main_splitter.setSizes([left, max(right, 200)])
            self._ensure_splitter_integrity()

    def _export_chapter(self, chapter_number: int) -> None:
        """
        Export all pages of the given chapter into <chapter>/<target_lang>/.

        For each page:
          - tries to find PageSession in memory;
          - if not found, but session_path exists вЂ“ tries to load from disk;
          - if no session at all вЂ“ skips the page.
        """
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_project_title", lang),
                tr("msg.no_project", lang),
            )
            return

        dst_lang = self.current_project.target_language or "ru"
        pages = self.current_project.pages
        chapter_pages: list[tuple[int, PageInfo]] = [
            (i, p) for i, p in enumerate(pages) if p.chapter_number == chapter_number
        ]

        if not chapter_pages:
            QtWidgets.QMessageBox.information(
                self,
                tr("msg.no_data", lang),
                tr("msg.no_pages_for_chapter", lang).format(chapter=chapter_number),
            )
            return

        exported: list[Path] = []
        skipped: list[int] = []

        for page_index, page_info in chapter_pages:
            session = self.page_sessions.get(page_index)

            if session is None and page_info.session_path is not None and page_info.session_path.is_file():
                try:
                    session = load_page_session(page_info.session_path.parent, page_index)
                    self.page_sessions[page_index] = session
                    normalized_path = self._normalized_path_for_page(page_info)
                    page_info.normalized_path = normalized_path
                    session.image_path = normalized_path
                    if session.original_image_path is None:
                        session.original_image_path = page_info.file_path
                    self._ensure_session_geometry(session, normalized_path, page_info)
                    session.page_width = getattr(self.current_project, "target_width", 0)
                    session.page_height = getattr(self.current_project, "target_height", 0)
                except Exception:
                    session = None

            if session is None:
                skipped.append(page_index)
                continue

            try:
                output_path = export_page_with_translations(
                    session,
                    dst_lang=dst_lang,
                    content_type=self.current_project.content_type,
                    color_mode=self.current_project.color_mode,
                )
            except Exception:
                skipped.append(page_index)
                continue

            exported.append(output_path)

        total = len(chapter_pages)
        ok_count = len(exported)
        skipped_count = len(skipped)

        msg_lines = [
            tr("msg.export_summary", lang).format(chapter=chapter_number),
            tr("msg.export_counts", lang).format(ok=ok_count, total=total),
        ]
        if skipped_count:
            human_indices = ", ".join(str(i + 1) for i in skipped)
            msg_lines.append(tr("msg.export_skipped", lang).format(pages=human_indices))

        QtWidgets.QMessageBox.information(
            self,
            tr("msg.export_chapter_title", lang),
            "\n".join(msg_lines),
        )

    # -------------------- navigation --------------------
    def _on_go_first_page(self) -> None:
        if self.current_project is None:
            return
        if self.current_page_index == 0:
            self._update_navigation_bar()
            return
        self._sync_current_editor_to_session()
        self.save_current_session_if_dirty()
        self.current_page_index = 0
        self._load_current_page()
        self._update_navigation_bar()

    def _on_go_prev_page(self) -> None:
        if self.current_project is None:
            return
        if self.current_page_index <= 0:
            self._update_navigation_bar()
            return
        try:
            self._sync_current_editor_to_session()
            self.save_current_session_if_dirty()
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Failed to save current page: {exc}")
        self.current_page_index -= 1
        self._load_current_page()
        self._update_navigation_bar()

    def _on_go_next_page(self) -> None:
        if self.current_project is None:
            return
        pages = self.current_project.pages
        if not pages:
            return
        if self.current_page_index >= len(pages) - 1:
            self._update_navigation_bar()
            return
        try:
            self._sync_current_editor_to_session()
            self.save_current_session_if_dirty()
        except Exception as exc:  # noqa: BLE001
            self.statusBar().showMessage(f"Failed to save current page: {exc}")
        self.current_page_index += 1
        self._load_current_page()
        self._update_navigation_bar()

    def _on_go_last_page(self) -> None:
        if self.current_project is None:
            return
        pages = self.current_project.pages
        if not pages:
            self._update_navigation_bar()
            return
        if self.current_page_index == len(pages) - 1:
            self._update_navigation_bar()
            return
        self._sync_current_editor_to_session()
        self.save_current_session_if_dirty()
        self.current_page_index = len(pages) - 1
        self._load_current_page()
        self._update_navigation_bar()

    # -------------------- core updates --------------------
    def _load_current_page(self) -> None:
        if self.current_project is None:
            return
        total_pages = len(self.current_project.pages)
        if total_pages == 0:
            return

        self.current_page_index = max(0, min(self.current_page_index, total_pages - 1))
        page_info: PageInfo = self.current_project.pages[self.current_page_index]

        normalized_path = self._normalized_path_for_page(page_info)
        page_info.normalized_path = normalized_path
        if not normalized_path.is_file():
            raise FileNotFoundError(f"Image file not found: {normalized_path}")

        pixmap = QtGui.QPixmap(str(normalized_path))
        if pixmap.isNull():
            raise ValueError(f"Failed to load image: {normalized_path}")

        sessions_dir = self._get_sessions_dir()
        session: Optional[PageSession] = self.page_sessions.get(self.current_page_index)
        json_path = sessions_dir / f"page_{self.current_page_index:04d}.json"
        if session is None and json_path.is_file():
            try:
                session = load_page_session(sessions_dir, self.current_page_index)
            except Exception:
                session = None

        if session is None:
            session = PageSession(
                project_id=self.current_project.title_id,
                page_index=self.current_page_index,
                image_path=normalized_path,
                original_image_path=page_info.file_path,
                text_blocks=[],
                src_lang=self.current_project.original_language,
                dst_lang=self.current_project.target_language,
                page_width=getattr(self.current_project, "target_width", pixmap.width()),
                page_height=getattr(self.current_project, "target_height", pixmap.height()),
            )
        session.image_path = normalized_path
        if session.original_image_path is None:
            session.original_image_path = page_info.file_path
        session.session_path = json_path if json_path.is_file() else None
        self._ensure_session_geometry(session, normalized_path, page_info)
        self.page_sessions[self.current_page_index] = session
        if session.session_path is not None:
            page_info.session_path = session.session_path
        self.current_session_dirty = False
        self._history.reset(session)

        visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
        page_info.ocr_done = bool(visible_blocks)
        page_info.translation_done = any((b.translated_text or "").strip() for b in visible_blocks)

        if hasattr(self.page_viewer_panel, "set_pixmap"):
            self.page_viewer_panel.set_pixmap(pixmap)
        elif hasattr(self.page_viewer_panel, "set_page"):
            self.page_viewer_panel.set_page(normalized_path)

        self.page_editor.set_page_session(session)
        self.page_viewer_panel.set_blocks(visible_blocks)
        self.page_viewer_panel.viewer.set_page_session(session)
        try:
            self.page_viewer_panel.viewer.zoom_fit_window()
        except Exception:
            pass
        self.translated_canvas.set_page_session(pixmap, session)
        try:
            self.translated_canvas.zoom_fit_window()
        except Exception:
            pass
        self._update_zoom_slider_from_canvas()

        self._set_visibility_state(
            mask=session.mask_enabled,
            text=session.text_enabled,
            sfx=session.show_sfx,
            mark_dirty=False,
        )

        if session.paint_layer_path:
            try:
                paint_image = QtGui.QImage(str(session.paint_layer_path))
                if not paint_image.isNull():
                    target_w = getattr(self.current_project, "target_width", paint_image.width())
                    target_h = getattr(self.current_project, "target_height", paint_image.height())
                    if paint_image.size() != QtCore.QSize(target_w, target_h):
                        paint_image = paint_image.scaled(
                            target_w,
                            target_h,
                            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                            QtCore.Qt.TransformationMode.SmoothTransformation,
                        )
                    self.translated_canvas.set_paint_layer_image(paint_image)
                    session.paint_layer_image = paint_image
            except Exception:
                pass

        self._ensure_splitter_integrity()

        self.statusBar().showMessage(
            f"Title: {self.current_project.title_name} | "
            f"Ch. {page_info.chapter_number}, page {page_info.page_in_chapter}"
        )

    def _update_navigation_bar(self) -> None:
        if self.current_project is None:
            self.page_viewer_panel.set_page_label("Page 0 / 0")
            self.page_viewer_panel.set_nav_enabled(False, False, False, False)
            return

        total = len(self.current_project.pages)
        current = self.current_page_index + 1
        page_info = self.current_project.pages[self.current_page_index]
        lang = self._current_language()
        self.page_viewer_panel.set_page_label(
            tr("nav.page_label", lang).format(
                chapter=page_info.chapter_number,
                page=page_info.page_in_chapter,
                current=current,
                total=total,
            )
        )

        has_project = self.current_project is not None and total > 0
        can_prev = has_project and self.current_page_index > 0
        can_next = has_project and self.current_page_index < total - 1
        self.page_viewer_panel.set_nav_enabled(can_prev, can_prev, can_next, can_next)

    # -------------------- retranslate --------------------
    def _on_retranslate_blocks_requested(self, block_ids: list[str]) -> None:
        lang = self._current_language()
        if self.current_project is None:
            QtWidgets.QMessageBox.information(
                self, tr("msg.no_project_title", lang), tr("msg.no_project", lang)
            )
            return

        session = self.page_sessions.get(self.current_page_index)
        if session is None:
            QtWidgets.QMessageBox.information(
                self, tr("msg.no_data", lang), tr("msg.no_session", lang)
            )
            return

        self._refresh_settings_cache()
        translator_settings = (
            self.settings_cache.get("translator", {}) if isinstance(self.settings_cache, dict) else {}
        )
        selected_translator_raw = translator_settings.get("selected", "")
        selected_translator = normalize_translator_id(selected_translator_raw)
        if not selected_translator:
            if not self._open_settings_dialog("translator"):
                QtWidgets.QMessageBox.information(
                    self, "Translator not configured", "Select a translator in Settings first."
                )
                return
            translator_settings = (
                self.settings_cache.get("translator", {}) if isinstance(self.settings_cache, dict) else {}
            )
            selected_translator = normalize_translator_id(translator_settings.get("selected", ""))
        translator_config: EngineConfig | None = get_translator_engine_config(selected_translator)
        translator_state: Dict[str, Any] = {}
        translator_engines_state = (
            translator_settings.get("engines", {}) if isinstance(translator_settings, dict) else {}
        )
        if isinstance(translator_engines_state, dict):
            translator_state = translator_engines_state.get(
                selected_translator, translator_engines_state.get(selected_translator_raw, {})
            )
        if translator_config is not None:
            translator_name = tr(getattr(translator_config, "name_key", translator_config.id), lang)
            if translator_config.mode == "offline" and not translator_state.get("downloaded"):
                QtWidgets.QMessageBox.information(
                    self,
                    tr("msg.error", lang),
                    f"{translator_name}: {tr('settings.status.not_downloaded', lang)}",
                )
                self.statusBar().showMessage(f"{translator_name} models are not downloaded yet.")
                return
            api_optional = getattr(translator_config, "api_optional", False)
            use_api = bool(translator_state.get("use_api", False)) if api_optional else True
            if translator_config.requires_api_key and (use_api or not api_optional):
                api_key = str(translator_state.get("api_key", "")).strip()
                endpoint = str(translator_state.get("endpoint", "")).strip()
                if not api_key or (translator_config.requires_endpoint and not endpoint):
                    QtWidgets.QMessageBox.warning(
                        self,
                        tr("msg.error", lang),
                        tr("error.enter_api_key", lang),
                    )
                    return
        project = self.current_project
        src_lang = project.original_language
        dst_lang = project.target_language

        deleted_blocks = [b for b in session.text_blocks if getattr(b, "deleted", False)]
        blocks_by_id = {b.id: b for b in session.text_blocks if not getattr(b, "deleted", False)}
        blocks_to_translate = []
        for block_id in block_ids:
            block = blocks_by_id.get(block_id)
            if block is None:
                continue

            original = (block.original_text or "").strip()
            if not original:
                continue
            blocks_to_translate.append(block)

        if not blocks_to_translate:
            return

        try:
            self.translation_service.translate_blocks(
                blocks=blocks_to_translate,
                project=project,
                engine_id=selected_translator,
                engine_state=translator_state,
                src_lang=src_lang,
                dst_lang=dst_lang,
            )
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, tr("msg.translation_error", lang), f"Failed to translate blocks: {exc}"
            )
            return

        if blocks_to_translate:
            session.text_blocks = deleted_blocks + list(blocks_by_id.values())
            visible_blocks = [b for b in session.text_blocks if not getattr(b, "deleted", False)]
            self.page_editor.set_page_session(session)
            page_info = self.current_project.pages[self.current_page_index]
            page_info.translation_done = any(
                (b.translated_text or "").strip() for b in visible_blocks
            )
            self.page_viewer_panel.set_blocks(visible_blocks)
            pixmap_path = session.image_path if session.image_path else page_info.file_path
            pixmap = QtGui.QPixmap(str(pixmap_path))
            if not pixmap.isNull():
                self.translated_canvas.set_page_session(pixmap, session)
            self.mark_current_session_dirty()
            self.statusBar().showMessage(
                tr("status.translation_updated", lang).format(
                    count=len(blocks_to_translate), page=self.current_page_index + 1
                )
            )

    # -------------------- close --------------------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        """On window close, attempt to sync and save current page session if needed."""
        try:
            self._sync_current_editor_to_session()
            self.save_current_session_if_dirty()
            event.accept()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(
                self, tr("msg.error", self._current_language()), f"Не удалось сохранить изменения:\n{exc}"
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _on_title_settings_applied(self) -> None:
        """Refresh runtime state after title settings were updated."""
        project = self.current_project
        if project is None:
            return
        # Update window title or other UI if needed.
        self.setWindowTitle(f"{APP_NAME} - {project.title_name}")
        # Refresh OCR engine language if needed.
        try:
            self.ocr_engine.src_lang = project.original_language
        except Exception:
            pass
        # Mark sessions dirty if language impacts pipeline; future OCR/translation will use new langs.
        self._refresh_settings_cache(refresh_canvas=False)
        self.mark_current_session_dirty()

