"""Dialogs for Blume Manga Translator."""
from __future__ import annotations

import shutil
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from config import (
    APP_NAME,
    BASE_PATH,
    FONTS_REGISTRY,
    app_config,
    has_font_family,
    init_fonts,
)
from core.engines_registry import OCR_ENGINES, EngineConfig, get_engine_models_dir, normalize_engine_id
from models.download_manager import DownloadStatus, delete_engine, download_engine, get_download_status, set_download_status
from i18n import tr
from languages import SUPPORTED_LANGS, get_display_name
from project.loader import save_project_meta
from project.models import TitleProject
from project.resolution_presets import PRESETS, ResolutionPreset, get_preset_by_id
from settings_manager import (
    DEFAULT_SETTINGS,
    load_effective_settings,
    save_global_settings,
    save_project_settings,
)
from fonts.presets import FONT_PRESETS, apply_preset, detect_preset
from translator.registry import list_translator_engines, normalize_translator_id

# -------------------- basic dialogs --------------------
class TitleSettingsDialog(QtWidgets.QDialog):
    """Dialog for selecting title languages and saving metadata."""

    def __init__(
        self,
        project: TitleProject,
        parent: Optional[QtWidgets.QWidget] = None,
        language: str = "en",
    ) -> None:
        super().__init__(parent)
        self.language = language
        self.setWindowTitle(tr("title.settings", language))
        self._project = project

        self.original_combo = QtWidgets.QComboBox(self)
        self.target_combo = QtWidgets.QComboBox(self)
        self.skip_sfx_checkbox = QtWidgets.QCheckBox(
            tr("label.skip_sfx_default", language), self
        )
        self._populate_lang_combo(self.original_combo)
        self._populate_lang_combo(self.target_combo)
        idx = self.original_combo.findData(project.original_language)
        self.original_combo.setCurrentIndex(idx if idx >= 0 else 0)
        idx = self.target_combo.findData(project.target_language)
        self.target_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.skip_sfx_checkbox.setChecked(bool(getattr(project, "skip_sfx_by_default", True)))

        self.content_type_combo = QtWidgets.QComboBox(self)
        self.content_type_combo.addItem(tr("option.standard", language), userData="standard")
        self.content_type_combo.addItem(tr("option.adult", language), userData="adult")
        idx = self.content_type_combo.findData(project.content_type)
        self.content_type_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.color_mode_combo = QtWidgets.QComboBox(self)
        self.color_mode_combo.addItem(tr("option.bw", language), userData="bw")
        self.color_mode_combo.addItem(tr("option.color", language), userData="color")
        idx = self.color_mode_combo.findData(project.color_mode)
        self.color_mode_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # Resolution preset + custom size
        self.resolution_combo = QtWidgets.QComboBox(self)
        self.resolution_combo.addItem("Custom", userData="custom")
        for preset in PRESETS:
            self.resolution_combo.addItem(preset.label, userData=preset.id)

        self.width_spin = QtWidgets.QSpinBox(self)
        self.width_spin.setRange(600, 8000)
        self.height_spin = QtWidgets.QSpinBox(self)
        self.height_spin.setRange(800, 12000)
        self.resolution_desc = QtWidgets.QLabel(self)
        self.resolution_desc.setWordWrap(True)

        initial_preset_id = getattr(project, "resolution_preset_id", "custom") or "custom"
        preset_idx = self.resolution_combo.findData(initial_preset_id)
        if preset_idx < 0:
            preset_idx = 0
        self.resolution_combo.setCurrentIndex(preset_idx)

        initial_w = int(getattr(project, "target_width", 0) or 0)
        initial_h = int(getattr(project, "target_height", 0) or 0)
        if initial_w <= 0 or initial_h <= 0:
            preset = get_preset_by_id(initial_preset_id)
            if preset:
                initial_w, initial_h = preset.width, preset.height
        self.width_spin.setValue(max(600, initial_w or 1600))
        self.height_spin.setValue(max(800, initial_h or 2400))
        self.resolution_combo.currentIndexChanged.connect(self._on_resolution_preset_changed)
        self._on_resolution_preset_changed(self.resolution_combo.currentIndex())

        form = QtWidgets.QFormLayout()
        form.addRow(tr("label.original_language", language), self.original_combo)
        form.addRow(tr("label.target_language", language), self.target_combo)
        form.addRow(self.skip_sfx_checkbox)
        form.addRow(tr("label.content_type", language), self.content_type_combo)
        form.addRow(tr("label.color_mode", language), self.color_mode_combo)
        form.addRow("Page resolution preset", self.resolution_combo)
        size_row = QtWidgets.QHBoxLayout()
        size_row.addWidget(QtWidgets.QLabel("Width", self))
        size_row.addWidget(self.width_spin)
        size_row.addWidget(QtWidgets.QLabel("Height", self))
        size_row.addWidget(self.height_spin)
        size_row.addStretch(1)
        form.addRow("Target size", size_row)
        form.addRow("", self.resolution_desc)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_resolution_preset_changed(self, idx: int) -> None:
        preset_id = self.resolution_combo.itemData(idx)
        preset: ResolutionPreset | None = get_preset_by_id(preset_id)
        if preset:
            self.width_spin.blockSignals(True)
            self.height_spin.blockSignals(True)
            self.width_spin.setValue(preset.width)
            self.height_spin.setValue(preset.height)
            self.width_spin.blockSignals(False)
            self.height_spin.blockSignals(False)
            self.width_spin.setEnabled(False)
            self.height_spin.setEnabled(False)
            self.resolution_desc.setText(preset.description)
        else:
            self.width_spin.setEnabled(True)
            self.height_spin.setEnabled(True)
            self.resolution_desc.setText("Set a custom target size to match your scans.")

    def accept(self) -> None:  # type: ignore[override]
        orig_code = self.original_combo.currentData() or self.original_combo.currentText()
        tgt_code = self.target_combo.currentData() or self.target_combo.currentText()
        self._project.original_language = orig_code
        self._project.target_language = tgt_code
        self._project.skip_sfx_by_default = bool(self.skip_sfx_checkbox.isChecked())
        self._project.content_type = self.content_type_combo.currentData() or "standard"
        self._project.color_mode = self.color_mode_combo.currentData() or "bw"
        preset_id = self.resolution_combo.currentData() or "custom"
        preset = get_preset_by_id(preset_id)
        if preset is not None:
            self._project.target_width = preset.width
            self._project.target_height = preset.height
            self._project.resolution_preset_id = preset.id
        else:
            self._project.target_width = int(self.width_spin.value())
            self._project.target_height = int(self.height_spin.value())
            self._project.resolution_preset_id = "custom"
        save_project_meta(self._project)
        super().accept()

    def _populate_lang_combo(self, combo: QtWidgets.QComboBox) -> None:
        combo.clear()
        for code, meta in SUPPORTED_LANGS.items():
            combo.addItem(get_display_name(code), userData=code)


class ResolutionSuggestionDialog(QtWidgets.QDialog):
    """Dialog that suggests a resolution preset based on detected stats."""

    def __init__(
        self,
        stats: Dict[str, Any],
        parent: Optional[QtWidgets.QWidget] = None,
        language: str = "en",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Page resolution")
        self.selected_preset_id: Optional[str] = None
        self.keep_original_size: bool = False

        median_w = stats.get("median_width", 0)
        median_h = stats.get("median_height", 0)
        too_low = median_w < 900 or median_h < 1200
        too_high = median_w > 2800 or median_h > 4200

        observed = QtWidgets.QLabel(f"Detected median size: {median_w}×{median_h}")
        observed.setWordWrap(True)

        warn_text = ""
        if too_low:
            warn_text = "Pages look low-resolution. OCR and rendering may be blurry."
        elif too_high:
            warn_text = "Pages are very high-resolution. Performance may be affected."
        warning = QtWidgets.QLabel(warn_text)
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #cc7722;")

        self.btn_std = QtWidgets.QPushButton("Use Standard preset", self)
        self.btn_std.clicked.connect(lambda: self._choose("std_manga"))
        self.btn_hi = QtWidgets.QPushButton("Use High-res preset", self)
        self.btn_hi.clicked.connect(lambda: self._choose("hires_manga"))
        self.btn_keep = QtWidgets.QPushButton("Keep original resolution", self)
        self.btn_keep.clicked.connect(self._choose_keep)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addWidget(self.btn_std)
        btn_layout.addWidget(self.btn_hi)
        btn_layout.addWidget(self.btn_keep)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(observed)
        if warn_text:
            layout.addWidget(warning)
        layout.addLayout(btn_layout)

    def _choose(self, preset_id: str) -> None:
        self.selected_preset_id = preset_id
        self.accept()

    def _choose_keep(self) -> None:
        self.keep_original_size = True
        self.selected_preset_id = None
        self.accept()


class AboutDialog(QtWidgets.QDialog):
    """Simple About dialog for the application."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, language: str = "en") -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("title.about", language))
        label = QtWidgets.QLabel(
            tr("msg.about_text", language).format(app=APP_NAME), self
        )
        label.setAlignment(QtCore.Qt.AlignCenter)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(label)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok, parent=self)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


# -------------------- settings data --------------------
def _format_size_text(engine: EngineConfig) -> str:
    """Return human-readable size for UI label."""
    if engine.mode == "cloud":
        return ""
    if engine.estimated_size_mb:
        return f"~{engine.estimated_size_mb} MB"
    return ""


# -------------------- settings UI helpers --------------------
class EngineCard(QtWidgets.QGroupBox):
    """Reusable card that shows an engine with status, description and fields."""

    class DownloadWorker(QtCore.QThread):
        progress = QtCore.Signal(int, int, float, str, float)  # idx, total, percent (0-100), name, MB/s
        file_finished = QtCore.Signal(int, int)
        finished_with_paths = QtCore.Signal(list)
        failed = QtCore.Signal(str)

        def __init__(self, engine_id: str, urls: list[str], target_dir: Path) -> None:
            super().__init__()
            self.engine_id = engine_id
            self.urls = list(urls)
            self.target_dir = target_dir

        def run(self) -> None:  # noqa: D401 - Qt thread
            paths: list[Path] = []
            try:
                total_files = len(self.urls)
                self.target_dir.mkdir(parents=True, exist_ok=True)
                for idx, url in enumerate(self.urls, start=1):
                    filename = url.split("/")[-1] or f"{self.engine_id}_{int(time.time())}"
                    dest = self.target_dir / filename
                    with urllib.request.urlopen(url) as response, open(dest, "wb") as fh:
                        total_size = int(response.headers.get("Content-Length", "0") or 0)
                        downloaded = 0
                        started = time.monotonic()
                        last_emit = started
                        while True:
                            chunk = response.read(256 * 1024)
                            if not chunk:
                                break
                            fh.write(chunk)
                            downloaded += len(chunk)
                            now = time.monotonic()
                            if now - last_emit >= 0.2:
                                speed_mb_s = (downloaded / 1024 / 1024) / max(now - started, 1e-3)
                                percent = (downloaded / total_size * 100) if total_size > 0 else 0.0
                                self.progress.emit(idx, total_files, percent, filename, speed_mb_s)
                                last_emit = now
                        # emit final state for file
                        speed_mb_s = (downloaded / 1024 / 1024) / max(time.monotonic() - started, 1e-3)
                        percent = 100.0 if total_size > 0 else 0.0
                        self.progress.emit(idx, total_files, percent, filename, speed_mb_s)
                    paths.append(dest)
                    self.file_finished.emit(idx, total_files)
                self.finished_with_paths.emit(paths)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))

    def __init__(
        self,
        engine: EngineConfig,
        saved: Dict[str, Any],
        button_group: QtWidgets.QButtonGroup,
        language: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.engine_id = engine.id
        self.language = language
        self.engine_name = tr(getattr(engine, "name_key", ""), language)
        self.description_text = tr(getattr(engine, "description_key", ""), language)
        self.is_offline = engine.mode == "offline"
        self.api_optional = bool(getattr(engine, "api_optional", False))
        self.supports_api = bool(getattr(engine, "supports_api", False) or engine.requires_api_key or self.api_optional)
        self.supports_scrape_mode = bool(getattr(engine, "supports_scrape_mode", False))
        self.requires_api = bool(engine.requires_api_key and not self.api_optional)
        self.requires_endpoint = engine.requires_endpoint
        self.download_urls = list(engine.download_urls or [])
        self._downloaded = (
            get_download_status(self.engine_id) == DownloadStatus.DOWNLOADED if self.is_offline else True
        )
        saved_api_key = saved.get("api_key", "")
        saved_endpoint = saved.get("endpoint", "")
        self._use_api = (
            bool(saved.get("use_api", False) or saved_api_key) if (self.api_optional or self.supports_scrape_mode) else True
        )
        if self.requires_api:
            self._use_api = True
        self._api_valid = bool(saved.get("api_valid", False))
        if not self.requires_api and not self._use_api:
            self._api_valid = True

        self.radio = QtWidgets.QRadioButton(self.engine_name, self)
        button_group.addButton(self.radio)

        self.status_label: QtWidgets.QLabel = QtWidgets.QLabel(self)
        self.download_button: Optional[QtWidgets.QPushButton] = None
        self.delete_button: Optional[QtWidgets.QPushButton] = None
        self.download_progress = QtWidgets.QProgressBar(self)
        self.download_progress.setVisible(False)
        self.download_speed_label = QtWidgets.QLabel(self)
        self.download_speed_label.setVisible(False)
        self._download_worker: Optional[EngineCard.DownloadWorker] = None

        if self.is_offline:
            self.download_button = QtWidgets.QPushButton(tr("settings.button.download", language), self)
            self.download_button.clicked.connect(self._mark_downloaded)
            self.download_progress.setRange(0, 1)
            self.download_progress.setValue(0)
            self.delete_button = QtWidgets.QPushButton(tr("settings.button.delete", language), self)
            self.delete_button.clicked.connect(self._delete_models)

        desc_label = QtWidgets.QLabel(self.description_text, self)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #666;")

        size_text = _format_size_text(engine)
        self.size_label: Optional[QtWidgets.QLabel] = None
        if size_text:
            size_prefix = tr("settings.size.label", language)
            self.size_label = QtWidgets.QLabel(f"{size_prefix} {size_text}", self)
            self.size_label.setStyleSheet("color: #666;")

        self.api_toggle_btn: Optional[QtWidgets.QPushButton] = None
        self.api_fields_widget: Optional[QtWidgets.QWidget] = None
        self.api_edit: Optional[QtWidgets.QLineEdit] = None
        self.api_check_btn: Optional[QtWidgets.QPushButton] = None
        self.endpoint_edit: Optional[QtWidgets.QLineEdit] = None

        if self.supports_api or self.requires_endpoint:
            if self.api_optional or self.supports_scrape_mode:
                self.api_toggle_btn = QtWidgets.QPushButton(tr("settings.translator.have_api_button", language), self)
                self.api_toggle_btn.setCheckable(True)
                self.api_toggle_btn.setChecked(self._use_api)
                self.api_toggle_btn.clicked.connect(self._on_api_toggle)

            self.api_fields_widget = QtWidgets.QWidget(self)
            api_form = QtWidgets.QFormLayout(self.api_fields_widget)
            if self.supports_api:
                api_row = QtWidgets.QHBoxLayout()
                self.api_edit = QtWidgets.QLineEdit(self.api_fields_widget)
                self.api_edit.setText(str(saved_api_key))
                self.api_edit.setPlaceholderText(tr("settings.translator.api_key", language))
                self.api_edit.textChanged.connect(self._invalidate_api)
                api_row.addWidget(self.api_edit)
                self.api_check_btn = QtWidgets.QPushButton(tr("settings.button.check", language), self.api_fields_widget)
                self.api_check_btn.clicked.connect(self._validate_api)
                api_row.addWidget(self.api_check_btn)
                api_form.addRow(tr("settings.translator.api_key", language), api_row)
            if self.requires_endpoint:
                self.endpoint_edit = QtWidgets.QLineEdit(self.api_fields_widget)
                self.endpoint_edit.setText(str(saved_endpoint))
                self.endpoint_edit.setPlaceholderText(tr("settings.translator.endpoint", language))
                self.endpoint_edit.textChanged.connect(self._invalidate_api)
                api_form.addRow(tr("settings.translator.endpoint", language), self.endpoint_edit)

        layout = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.radio)
        header.addStretch(1)
        header.addWidget(self.status_label)
        layout.addLayout(header)

        layout.addWidget(desc_label)
        if self.size_label is not None:
            layout.addWidget(self.size_label)

        if self.api_toggle_btn is not None:
            layout.addWidget(self.api_toggle_btn)
        if self.api_fields_widget is not None:
            layout.addWidget(self.api_fields_widget)

        if self.is_offline and self.download_button is not None:
            btn_line = QtWidgets.QHBoxLayout()
            btn_line.addWidget(self.download_button)
            if self.delete_button:
                btn_line.addWidget(self.delete_button)
            btn_line.addWidget(self.download_progress, 1)
            btn_line.addWidget(self.download_speed_label)
            btn_line.addStretch(1)
            layout.addLayout(btn_line)

        self._update_api_visibility()
        self._update_status()

    def _update_api_visibility(self) -> None:
        if self.api_fields_widget is not None:
            show_api = self.requires_api or self._use_api
            self.api_fields_widget.setVisible(show_api)
            if self.api_edit is not None:
                self.api_edit.setEnabled(show_api)
            if self.api_check_btn is not None:
                self.api_check_btn.setEnabled(show_api)
            if self.endpoint_edit is not None:
                self.endpoint_edit.setEnabled(show_api)
        if self.api_toggle_btn is not None:
            text_key = "settings.translator.hide_api_button" if self._use_api else "settings.translator.have_api_button"
            self.api_toggle_btn.setText(tr(text_key, self.language))

    def _has_required_api_inputs(self) -> bool:
        if not (self.supports_api or self.requires_endpoint):
            return True
        if self.api_optional and not self._use_api and self.supports_scrape_mode:
            return True
        has_key = bool(self.api_edit and self.api_edit.text().strip())
        endpoint_ok = True
        if self.requires_endpoint:
            endpoint_ok = bool(self.endpoint_edit and self.endpoint_edit.text().strip())
        if self.requires_api or self._use_api:
            return has_key and endpoint_ok
        return True

    def _update_status(self) -> None:
        api_ready = self._has_required_api_inputs()
        status_text = tr("settings.status.configured", self.language)
        if self.is_offline and self.status_label is not None:
            status_text = (
                tr("settings.status.downloaded", self.language)
                if self._downloaded
                else tr("settings.status.not_downloaded", self.language)
            )
            if self.download_button:
                self.download_button.setEnabled(not self._downloaded)
            if self.delete_button:
                self.delete_button.setVisible(self._downloaded)
                self.delete_button.setEnabled(self._downloaded)
        elif (self.requires_api or self._use_api) and not api_ready:
            status_text = tr("settings.status.not_configured", self.language)

        if self.status_label is not None:
            self.status_label.setText(f"{tr('settings.status.label', self.language)} {status_text}")

        can_select = (not self.is_offline or self._downloaded) and api_ready
        self.radio.setEnabled(can_select)
        if not can_select and self.radio.isChecked():
            self.radio.setChecked(False)

    def _on_api_toggle(self, checked: bool) -> None:
        self._use_api = bool(checked)
        if not self.requires_api and not self._use_api:
            self._api_valid = True
        self._update_api_visibility()
        self._update_status()

    def _mark_downloaded(self) -> None:
        if not self.is_offline:
            return
        if not self.download_urls:
            QtWidgets.QMessageBox.warning(
                self,
                "Download",
                tr("error.no_download_url", self.language),
            )
            return

        if self._download_worker is not None:
            return

        target_dir = get_engine_models_dir(self.engine)
        total_files = len(self.download_urls)
        if self.download_button:
            self.download_button.setEnabled(False)
        self.download_progress.setVisible(True)
        self.download_progress.setRange(0, total_files * 100)
        self.download_progress.setValue(0)
        self.download_speed_label.setVisible(True)
        self.download_speed_label.setText("")

        self._download_worker = EngineCard.DownloadWorker(self.engine_id, self.download_urls, target_dir)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.file_finished.connect(self._on_download_file_finished)
        self._download_worker.finished_with_paths.connect(self._on_download_finished)
        self._download_worker.failed.connect(self._on_download_failed)
        self._download_worker.finished.connect(self._clear_worker)
        self._download_worker.start()

    def _download_file(self, url: str, target_dir: Path) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = url.split("/")[-1] or f"{self.engine_id}_{int(time.time())}"
        dest = target_dir / filename
        with urllib.request.urlopen(url) as response, open(dest, "wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
        return dest

    def _extract_if_needed(self, file_path: Path, target_dir: Path) -> None:
        suffix = file_path.suffix.lower()
        name = file_path.name.lower()
        try:
            if suffix == ".zip":
                with zipfile.ZipFile(file_path, "r") as zf:
                    zf.extractall(target_dir)
            elif suffix in {".tar", ".gz", ".tgz"} or name.endswith(".tar.gz"):
                with tarfile.open(file_path, "r:*") as tf:
                    tf.extractall(target_dir)
        except (tarfile.TarError, zipfile.BadZipFile):
            # Ignore extraction errors and keep the downloaded archive as-is.
            pass

    @QtCore.Slot(int, int, float, str, float)
    def _on_download_progress(self, idx: int, total: int, percent: float, filename: str, speed_mb_s: float) -> None:
        safe_percent = max(0.0, min(percent, 100.0))
        overall = int((idx - 1) * 100 + safe_percent)
        self.download_progress.setValue(overall)
        self.download_speed_label.setText(
            f"{idx}/{total} - {safe_percent:.1f}% ({speed_mb_s:.2f} MB/s) {filename}"
        )

    @QtCore.Slot(int, int)
    def _on_download_file_finished(self, idx: int, total: int) -> None:
        self.download_speed_label.setText(f"{idx}/{total} - {tr('settings.status.downloaded', self.language)}")

    @QtCore.Slot(list)
    def _on_download_finished(self, paths: list[Path]) -> None:
        try:
            target_dir = get_engine_models_dir(self.engine)
            for p in paths:
                self._extract_if_needed(p, target_dir)
            self.mark_downloaded_success()
            QtWidgets.QMessageBox.information(self, "Download", tr("settings.status.downloaded", self.language))
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Download", f"Failed to process downloaded models: {exc}")
        finally:
            self.download_progress.setVisible(False)
            self.download_speed_label.setVisible(False)
            if self.download_button:
                self.download_button.setEnabled(not self._downloaded)
            self._update_status()

    @QtCore.Slot(str)
    def _on_download_failed(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Download", f"Failed to download models: {message}")
        self.download_progress.setVisible(False)
        self.download_speed_label.setVisible(False)
        if self.download_button:
            self.download_button.setEnabled(not self._downloaded)
        self._update_status()

    @QtCore.Slot()
    def _clear_worker(self) -> None:
        self._download_worker = None

    def _delete_models(self) -> None:
        if not self.is_offline:
            return
        target_dir = get_engine_models_dir(self.engine)
        if not target_dir.exists():
            QtWidgets.QMessageBox.information(self, "Delete", tr("info.nothing_to_delete", self.language))
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            tr("actions.delete", self.language),
            tr("confirm.delete_models", self.language),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            shutil.rmtree(target_dir, ignore_errors=False)
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "Delete", f"Failed to remove models: {exc}")
            return
        self._downloaded = False
        self._update_status()
        QtWidgets.QMessageBox.information(self, "Delete", tr("settings.status.not_downloaded", self.language))

    def mark_downloaded_success(self) -> None:
        self._downloaded = True
        self._update_status()

    def set_checked(self, value: bool) -> None:
        if not self.is_ready():
            return
        self.radio.setChecked(value)

    def is_checked(self) -> bool:
        return bool(self.radio.isChecked())

    def is_ready(self) -> bool:
        return (not self.is_offline or self._downloaded) and self._has_required_api_inputs()

    def get_values(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if self.is_offline:
            data["downloaded"] = self._downloaded
        if self.supports_api:
            data["use_api"] = bool(self._use_api)
            if self.api_edit:
                data["api_key"] = self.api_edit.text().strip()
                data["api_valid"] = bool(
                    self._api_valid
                    or (self._use_api and self._has_required_api_inputs())
                    or (not self._use_api and self.api_optional)
                )
        if self.requires_endpoint and self.endpoint_edit:
            data["endpoint"] = self.endpoint_edit.text().strip()
        return data

    def _invalidate_api(self) -> None:
        self._api_valid = False if self._use_api or self.requires_api else True
        self._update_status()

    def _validate_api(self) -> None:
        self._api_valid = self._has_required_api_inputs()
        if self._api_valid:
            QtWidgets.QMessageBox.information(self, "API", tr("settings.translator.api_check_success", self.language))
        else:
            QtWidgets.QMessageBox.warning(self, "API", tr("settings.translator.api_check_failed", self.language))
        self._update_status()


class GeneralSettingsTab(QtWidgets.QWidget):
    """General settings: UI language, startup behavior, autosave."""

    def __init__(
        self, settings: Dict[str, Any], language: str, parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.language = language

        base = DEFAULT_SETTINGS.get("general", {})
        ui_language = settings.get("ui_language", base.get("ui_language", "en"))
        open_last = bool(settings.get("open_last_project", base.get("open_last_project", False)))
        autosave_enabled = bool(settings.get("autosave_enabled", base.get("autosave_enabled", False)))
        autosave_interval = int(
            settings.get("autosave_interval_min", base.get("autosave_interval_min", 5))
        )
        default_resolution_preset = settings.get(
            "default_resolution_preset", base.get("default_resolution_preset", "ask")
        )

        self.lang_combo = QtWidgets.QComboBox(self)
        self.lang_combo.addItem("English (en)", userData="en")
        self.lang_combo.addItem("Р СѓСЃСЃРєРёР№ (ru)", userData="ru")
        idx = self.lang_combo.findData(ui_language)
        self.lang_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.open_last_checkbox = QtWidgets.QCheckBox(tr("general.open_last", language), self)
        self.open_last_checkbox.setChecked(open_last)

        self.autosave_checkbox = QtWidgets.QCheckBox(tr("general.autosave", language), self)
        self.autosave_checkbox.setChecked(autosave_enabled)

        self.autosave_spin = QtWidgets.QSpinBox(self)
        self.autosave_spin.setRange(1, 120)
        self.autosave_spin.setSuffix(f" {tr('general.autosave_suffix', language)}")
        self.autosave_spin.setValue(max(1, autosave_interval))
        self.autosave_spin.setEnabled(autosave_enabled)
        self.autosave_checkbox.toggled.connect(self.autosave_spin.setEnabled)

        self.default_resolution_combo = QtWidgets.QComboBox(self)
        self.default_resolution_combo.addItem("Ask every time", userData="ask")
        for preset in PRESETS:
            self.default_resolution_combo.addItem(preset.label, userData=preset.id)
        idx = self.default_resolution_combo.findData(default_resolution_preset)
        self.default_resolution_combo.setCurrentIndex(idx if idx >= 0 else 0)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        form.setFormAlignment(QtCore.Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.addRow(tr("general.language", language), self.lang_combo)
        form.addRow(tr("general.open_last", language), self.open_last_checkbox)
        form.addRow(tr("general.autosave", language), self.autosave_checkbox)
        form.addRow(tr("general.autosave_interval", language), self.autosave_spin)
        form.addRow("Default page resolution", self.default_resolution_combo)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(form)
        layout.addStretch(1)

    def get_values(self) -> Dict[str, Any]:
        return {
            "ui_language": self.lang_combo.currentData() or "en",
            "open_last_project": bool(self.open_last_checkbox.isChecked()),
            "autosave_enabled": bool(self.autosave_checkbox.isChecked()),
            "autosave_interval_min": int(self.autosave_spin.value()),
            "default_resolution_preset": self.default_resolution_combo.currentData() or "ask",
        }


class OCRSettingsTab(QtWidgets.QWidget):
    """OCR engines: selection, download status, API keys."""

    def __init__(
        self, settings: Dict[str, Any], language: str, parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.cards: Dict[str, EngineCard] = {}
        self.button_group = QtWidgets.QButtonGroup(self)
        self.button_group.setExclusive(True)

        engines_settings = settings.get("engines", {}) if isinstance(settings, dict) else {}
        normalized_engines = (
            {normalize_engine_id(key): value for key, value in engines_settings.items()}
            if isinstance(engines_settings, dict)
            else {}
        )
        selected_engine = normalize_engine_id(settings.get("selected", ""))

        container = QtWidgets.QWidget(self)
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)

        for engine in OCR_ENGINES:
            saved = normalized_engines.get(engine.id, {}) if isinstance(normalized_engines, dict) else {}
            card = EngineCard(engine, saved, self.button_group, language, self)
            card.set_checked(engine.id == selected_engine)
            self.cards[engine.id] = card
            vbox.addWidget(card)

        vbox.addStretch(1)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(container)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(scroll)

        has_checked = any(card.is_checked() for card in self.cards.values())
        if not has_checked:
            for engine in OCR_ENGINES:
                card = self.cards.get(engine.id)
                if card and card.is_ready():
                    card.set_checked(True)
                    break

    def get_values(self) -> Dict[str, Any]:
        selected = ""
        for engine_id, card in self.cards.items():
            if card.is_checked():
                selected = engine_id
                break

        if not selected:
            for engine_id, card in self.cards.items():
                if card.is_ready():
                    selected = engine_id
                    break

        engines_data = {engine_id: card.get_values() for engine_id, card in self.cards.items()}
        return {"selected": selected, "engines": engines_data}


class TranslatorSettingsTab(QtWidgets.QWidget):
    """Translator engines: selection, download status, API keys."""

    def __init__(
        self, settings: Dict[str, Any], language: str, parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.cards: Dict[str, EngineCard] = {}
        self.button_group = QtWidgets.QButtonGroup(self)
        self.button_group.setExclusive(True)

        engines_settings = settings.get("engines", {}) if isinstance(settings, dict) else {}
        normalized_engines = (
            {normalize_translator_id(key): value for key, value in engines_settings.items()}
            if isinstance(engines_settings, dict)
            else {}
        )
        selected_engine = normalize_translator_id(settings.get("selected", ""))

        container = QtWidgets.QWidget(self)
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)

        for engine in list_translator_engines():
            saved = normalized_engines.get(engine.id, {}) if isinstance(normalized_engines, dict) else {}
            card = EngineCard(engine, saved, self.button_group, language, self)
            card.set_checked(engine.id == selected_engine)
            self.cards[engine.id] = card
            vbox.addWidget(card)

        vbox.addStretch(1)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(container)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(scroll)

        has_checked = any(card.is_checked() for card in self.cards.values())
        if not has_checked:
            for engine in list_translator_engines():
                card = self.cards.get(engine.id)
                if card and card.is_ready():
                    card.set_checked(True)
                    break

    def get_values(self) -> Dict[str, Any]:
        selected = ""
        for engine_id, card in self.cards.items():
            if card.is_checked():
                selected = engine_id
                break

        if not selected:
            for engine_id, card in self.cards.items():
                if card.is_ready():
                    selected = engine_id
                    break

        engines_data = {engine_id: card.get_values() for engine_id, card in self.cards.items()}
        return {"selected": selected, "engines": engines_data}


class AppearanceSettingsTab(QtWidgets.QWidget):
    """Appearance: scale, theme, fit mode."""

    def __init__(
        self,
        settings: Dict[str, Any],
        language: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.language = language

        base = DEFAULT_SETTINGS.get("appearance", {})
        scale = float(settings.get("scale", base.get("scale", 1.0)))
        theme = settings.get("theme", base.get("theme", "system"))
        fit_to_width = bool(settings.get("fit_to_width", base.get("fit_to_width", True)))

        self.scale_combo = QtWidgets.QComboBox(self)
        for value in (1.0, 1.25, 1.5, 1.75, 2.0):
            self.scale_combo.addItem(f"{value:.2f}x", userData=value)
        idx = self.scale_combo.findData(scale)
        self.scale_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.theme_combo = QtWidgets.QComboBox(self)
        self.theme_combo.addItem(tr("appearance.theme.system", language), userData="system")
        self.theme_combo.addItem(tr("appearance.theme.light", language), userData="light")
        self.theme_combo.addItem(tr("appearance.theme.dark", language), userData="dark")
        idx = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(idx if idx >= 0 else 0)

        self.fit_checkbox = QtWidgets.QCheckBox(tr("appearance.fit", language), self)
        self.fit_checkbox.setChecked(fit_to_width)

        form = QtWidgets.QFormLayout()
        form.addRow(tr("appearance.scale", language), self.scale_combo)
        form.addRow(tr("appearance.theme", language), self.theme_combo)
        form.addRow("", self.fit_checkbox)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch(1)

    def get_values(self) -> Dict[str, Any]:
        return {
            "scale": float(self.scale_combo.currentData() or 1.0),
            "theme": self.theme_combo.currentData() or "system",
            "fit_to_width": bool(self.fit_checkbox.isChecked()),
        }


class FontsSettingsTab(QtWidgets.QWidget):
    """Fonts tab: UI font, manga bubble font, optional SFX font."""

    def __init__(
        self,
        settings: Dict[str, Any],
        language: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.language = language
        self._base_path = BASE_PATH

        base = DEFAULT_SETTINGS.get("fonts", {})
        settings = settings or {}
        ui_font = settings.get("ui_font_family", base.get("ui_font_family"))
        manga_font = settings.get("manga_font_family", base.get("manga_font_family"))
        sfx_font = settings.get("sfx_font_family", base.get("sfx_font_family"))

        self.ui_combo = QtWidgets.QComboBox(self)
        self.manga_combo = QtWidgets.QComboBox(self)
        self.sfx_combo = QtWidgets.QComboBox(self)
        self.preset_combo = QtWidgets.QComboBox(self)

        self._populate_families()
        self._set_current(self.ui_combo, ui_font)
        self._set_current(self.manga_combo, manga_font)
        self._set_current(self.sfx_combo, sfx_font)
        self._populate_presets(ui_font, manga_font, sfx_font)

        self.ui_combo.currentIndexChanged.connect(self._on_manual_change)
        self.manga_combo.currentIndexChanged.connect(self._on_manual_change)
        self.sfx_combo.currentIndexChanged.connect(self._on_manual_change)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        self.add_font_btn = QtWidgets.QPushButton("Add custom font...", self)
        self.add_font_btn.clicked.connect(self._on_add_custom_font)

        form = QtWidgets.QFormLayout()
        form.addRow("Presets", self.preset_combo)
        form.addRow("UI font", self.ui_combo)
        form.addRow("Default manga font", self.manga_combo)
        form.addRow("SFX font", self.sfx_combo)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addLayout(form)
        layout.addWidget(self.add_font_btn)
        layout.addStretch(1)

    def _populate_families(self) -> None:
        families = sorted(FONTS_REGISTRY.keys())
        placeholders = [self.ui_combo, self.manga_combo, self.sfx_combo]
        for combo in placeholders:
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("<Default>", userData=None)
            for fam in families:
                combo.addItem(fam, userData=fam)
            combo.blockSignals(False)

    def _set_current(self, combo: QtWidgets.QComboBox, value: Any) -> None:
        if value is None:
            combo.setCurrentIndex(0)
            return
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _populate_presets(self, ui_font: Any, manga_font: Any, sfx_font: Any) -> None:
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItem("Custom", userData=None)
        for preset in FONT_PRESETS:
            self.preset_combo.addItem(preset.label, userData=preset.id)
        matched = detect_preset(ui_font, manga_font, sfx_font)
        if matched:
            idx = self.preset_combo.findData(matched.id)
            self.preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.preset_combo.setCurrentIndex(0)
        self.preset_combo.blockSignals(False)

    def _apply_preset(self, preset_id: str) -> None:
        preset = next((p for p in FONT_PRESETS if p.id == preset_id), None)
        if preset is None:
            return

        def set_combo(combo: QtWidgets.QComboBox, family: str) -> None:
            idx = combo.findData(family)
            if idx >= 0:
                combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(False)

        apply_preset(
            preset,
            FONTS_REGISTRY,
            lambda fam: set_combo(self.ui_combo, fam),
            lambda fam: set_combo(self.manga_combo, fam),
            lambda fam: set_combo(self.sfx_combo, fam),
        )

    def _on_manual_change(self) -> None:
        if self.preset_combo.currentIndex() != 0:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(0)
            self.preset_combo.blockSignals(False)

    def _on_preset_changed(self, idx: int) -> None:
        preset_id = self.preset_combo.itemData(idx)
        if preset_id:
            self._apply_preset(preset_id)

    def _on_add_custom_font(self) -> None:
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Add custom font...", str(self._base_path), "Font files (*.ttf *.otf)"
        )
        if not file_path:
            return

        ui_before = self.ui_combo.currentData()
        manga_before = self.manga_combo.currentData()
        sfx_before = self.sfx_combo.currentData()

        src = Path(file_path)
        target_dir = self._base_path / "resources" / "user_fonts"
        target_dir.mkdir(parents=True, exist_ok=True)
        dst = target_dir / src.name
        try:
            shutil.copy2(src, dst)
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Fonts", "Failed to copy font file.")
            return

        init_fonts()
        self._populate_families()
        self._set_current(self.ui_combo, ui_before)
        self._set_current(self.manga_combo, manga_before)
        self._set_current(self.sfx_combo, sfx_before)
        self._populate_presets(self.ui_combo.currentData(), self.manga_combo.currentData(), self.sfx_combo.currentData())

    def get_values(self) -> Dict[str, Any]:
        return {
            "ui_font_family": self.ui_combo.currentData(),
            "manga_font_family": self.manga_combo.currentData(),
            "sfx_font_family": self.sfx_combo.currentData(),
        }

# -------------------- settings dialog --------------------
class SettingsDialog(QtWidgets.QDialog):
    """Central settings dialog with tabs for all configuration groups."""

    settingsApplied = QtCore.Signal(dict)

    def __init__(
        self,
        project_folder: Optional[Path] = None,
        parent: Optional[QtWidgets.QWidget] = None,
        language: str = "en",
    ) -> None:
        super().__init__(parent)
        self._language = language or "en"
        self.setWindowTitle(tr("settings.title", self._language))
        self._project_folder = project_folder
        self._initial_settings = load_effective_settings(project_folder)
        self._current_settings = dict(self._initial_settings)

        self.tab_widget = QtWidgets.QTabWidget(self)
        self.general_tab = GeneralSettingsTab(self._initial_settings.get("general", {}), self._language, self)
        self.ocr_tab = OCRSettingsTab(self._initial_settings.get("ocr", {}), self._language, self)
        self.translator_tab = TranslatorSettingsTab(
            self._initial_settings.get("translator", {}), self._language, self
        )
        self.appearance_tab = AppearanceSettingsTab(
            self._initial_settings.get("appearance", {}), self._language, self
        )
        self.fonts_tab = FontsSettingsTab(self._initial_settings.get("fonts", {}), self._language, self)

        self.tab_widget.addTab(self.general_tab, tr("tabs.general", self._language))
        self.tab_widget.addTab(self.ocr_tab, tr("tabs.ocr", self._language))
        self.tab_widget.addTab(self.translator_tab, tr("tabs.translator", self._language))
        self.tab_widget.addTab(self.appearance_tab, tr("tabs.appearance", self._language))
        self.tab_widget.addTab(self.fonts_tab, "Fonts")

        buttons = QtWidgets.QDialogButtonBox(QtCore.Qt.Horizontal, self)
        self.btn_save = buttons.addButton(tr("buttons.save", self._language), QtWidgets.QDialogButtonBox.AcceptRole)
        self.btn_cancel = buttons.addButton(tr("buttons.cancel", self._language), QtWidgets.QDialogButtonBox.RejectRole)
        self.btn_apply = QtWidgets.QPushButton(tr("buttons.apply", self._language), self)
        buttons.addButton(self.btn_apply, QtWidgets.QDialogButtonBox.ApplyRole)

        self.btn_save.clicked.connect(self._on_save_and_close)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._on_apply)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.tab_widget)
        layout.addWidget(buttons)

    def open_tab(self, name: str) -> None:
        """Switch to the requested tab by name (case-insensitive)."""
        normalized = name.strip().lower()
        mapping = {
            "general": 0,
            "РѕР±С‰РёРµ": 0,
            "РѕСЃРЅРѕРІРЅС‹Рµ": 0,
            "ocr": 1,
            "РїРµСЂРµРІРѕРґС‡РёРє": 2,
            "translator": 2,
            "appearance": 3,
            "РІРЅРµС€РЅРёР№ РІРёРґ": 3,
            "fonts": 4,
            "шрифты": 4,
        }
        index = mapping.get(normalized)
        if index is not None:
            self.tab_widget.setCurrentIndex(index)

    def _collect_settings(self) -> Dict[str, Any]:
        updated = dict(self._initial_settings)

        updated["general"] = {
            **(self._initial_settings.get("general", {}) or {}),
            **self.general_tab.get_values(),
        }

        new_ocr = self.ocr_tab.get_values()
        merged_ocr = dict(self._initial_settings.get("ocr", {}) or {})
        merged_ocr.update({k: v for k, v in new_ocr.items() if k != "engines"})
        merged_engines: Dict[str, Any] = {}
        existing_engines_obj = merged_ocr.get("engines", {})
        existing_engines = existing_engines_obj if isinstance(existing_engines_obj, dict) else {}
        for engine_id, values in new_ocr.get("engines", {}).items():
            prev_values = existing_engines.get(engine_id, {}) if isinstance(existing_engines, dict) else {}
            merged = dict(prev_values)
            merged.update(values)
            merged_engines[engine_id] = merged
        merged_ocr["engines"] = merged_engines
        updated["ocr"] = merged_ocr

        new_translator = self.translator_tab.get_values()
        merged_translator = dict(self._initial_settings.get("translator", {}) or {})
        merged_translator.update({k: v for k, v in new_translator.items() if k != "engines"})
        merged_tr_engines: Dict[str, Any] = {}
        existing_tr_engines_obj = merged_translator.get("engines", {})
        existing_tr_engines = existing_tr_engines_obj if isinstance(existing_tr_engines_obj, dict) else {}
        for engine_id, values in new_translator.get("engines", {}).items():
            prev_values = existing_tr_engines.get(engine_id, {}) if isinstance(existing_tr_engines, dict) else {}
            merged = dict(prev_values)
            merged.update(values)
            merged_tr_engines[engine_id] = merged
        merged_translator["engines"] = merged_tr_engines
        updated["translator"] = merged_translator

        updated["appearance"] = {
            **(self._initial_settings.get("appearance", {}) or {}),
            **self.appearance_tab.get_values(),
        }

        updated["fonts"] = {
            **(self._initial_settings.get("fonts", {}) or {}),
            **self.fonts_tab.get_values(),
        }

        for key, value in DEFAULT_SETTINGS.items():
            if key not in updated:
                updated[key] = value
        return updated

    def _apply_fonts_settings(self) -> None:
        """Update runtime font settings after saving."""
        fonts_values = self.fonts_tab.get_values()
        app_config.ui_font_family = fonts_values.get("ui_font_family")
        app_config.manga_font_family = fonts_values.get("manga_font_family")
        app_config.sfx_font_family = fonts_values.get("sfx_font_family")

        app_instance = QtWidgets.QApplication.instance()
        if app_instance:
            if app_config.ui_font_family:
                app_instance.setFont(QtGui.QFont(app_config.ui_font_family, 9))
            else:
                app_instance.setFont(QtGui.QFont())

    def _save_settings(self) -> Dict[str, Any]:
        """Persist current UI values and emit an update signal."""
        self._current_settings = self._collect_settings()
        save_global_settings(self._current_settings)
        save_project_settings(self._project_folder, self._current_settings)
        self._apply_fonts_settings()
        snapshot = dict(self._current_settings)
        self.settingsApplied.emit(snapshot)
        return snapshot

    def _on_apply(self) -> None:
        self._save_settings()

    def _on_save_and_close(self) -> None:
        self._save_settings()
        self.accept()

    def get_updated_settings(self) -> Dict[str, Any]:
        """Return the latest settings snapshot after dialog completion."""
        return dict(self._current_settings)


