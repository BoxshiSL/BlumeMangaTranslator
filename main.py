"""Entry point for the Blume Manga Translator desktop application."""
from pathlib import Path

from PySide6 import QtGui, QtWidgets

from config import (
    DEFAULT_MANGA_FONT_FAMILY,
    DEFAULT_SFX_FONT_FAMILY,
    DEFAULT_UI_FONT_FAMILY,
    app_config,
    has_font_family,
    init_fonts,
    pick_default_font,
)
from settings_manager import load_effective_settings
from ui.main_window import MainWindow


def apply_theme(app: QtWidgets.QApplication, theme: str) -> None:
    """Apply light/dark stylesheet to the whole application."""
    theme = (theme or "system").lower()
    base = Path(__file__).resolve().parent / "resources" / "styles"
    qss_path = None
    if theme == "dark":
        qss_path = base / "dark.qss"
    elif theme == "light":
        qss_path = base / "light.qss"

    # Always clear the previous stylesheet before applying a new one to avoid stacking rules.
    app.setStyleSheet("")
    if qss_path is not None and qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def main() -> int:
    """Start the Qt application and show the main window."""
    app = QtWidgets.QApplication([])

    init_fonts()

    settings = load_effective_settings(None)
    fonts_settings = settings.get("fonts", {}) if isinstance(settings, dict) else {}
    app_config.ui_font_family = fonts_settings.get("ui_font_family") or pick_default_font(
        DEFAULT_UI_FONT_FAMILY
    )
    app_config.manga_font_family = fonts_settings.get("manga_font_family") or pick_default_font(
        DEFAULT_MANGA_FONT_FAMILY
    )
    app_config.sfx_font_family = fonts_settings.get("sfx_font_family") or pick_default_font(
        DEFAULT_SFX_FONT_FAMILY
    )
    theme_name = settings.get("appearance", {}).get("theme", "system") if isinstance(settings, dict) else "system"

    if app_config.ui_font_family and has_font_family(app_config.ui_font_family):
        app.setFont(QtGui.QFont(app_config.ui_font_family, 9))

    apply_theme(app, theme_name)

    window = MainWindow()
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
