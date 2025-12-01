"""Export pages to OpenRaster (.ora) layered files."""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

from export.model import ExportPageData, ExportTextBubble
from ui.text_layout import ResolvedBubbleStyle, apply_style_and_layout_text_item


def _save_qimage(image: QtGui.QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(path), "PNG")


def _render_text_layer(export_data: ExportPageData, bubble: ExportTextBubble, target: Path) -> None:
    img = QtGui.QImage(export_data.width, export_data.height, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.GlobalColor.transparent)

    scene = QtWidgets.QGraphicsScene()
    text_item = QtWidgets.QGraphicsTextItem(bubble.text)
    style = bubble.style
    resolved = ResolvedBubbleStyle(
        font_family=style.font_family,
        font_size=style.font_size,
        line_spacing=1.0,
        align=style.align,
    )
    rect = QtCore.QRectF(*bubble.rect)
    apply_style_and_layout_text_item(text_item, rect, resolved)
    scene.addItem(text_item)
    scene.setSceneRect(QtCore.QRectF(0, 0, export_data.width, export_data.height))

    painter = QtGui.QPainter(img)
    scene.render(painter)
    painter.end()
    _save_qimage(img, target)


def _create_mask_layer(export_data: ExportPageData, target: Path) -> None:
    img = QtGui.QImage(export_data.width, export_data.height, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(img)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    color = QtGui.QColor(*export_data.mask_color)
    painter.setBrush(QtGui.QBrush(color))
    for bubble in export_data.bubbles:
        if not bubble.enabled:
            continue
        if bubble.block_type == "sfx" and not export_data.show_sfx:
            continue
        rect = QtCore.QRectF(*bubble.rect)
        painter.drawRect(rect)
    painter.end()
    _save_qimage(img, target)


def _copy_or_save_paint_layer(export_data: ExportPageData, target: Path) -> bool:
    if export_data.paint_layer_path and Path(export_data.paint_layer_path).is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        QtGui.QImage(str(export_data.paint_layer_path)).save(str(target), "PNG")
        return True
    paint_image = getattr(export_data, "paint_layer_image", None)
    if paint_image is not None and isinstance(paint_image, QtGui.QImage) and not paint_image.isNull():
        _save_qimage(paint_image, target)
        return True
    return False


def _build_stack_xml(export_data: ExportPageData, text_layers: List[str], include_mask: bool, include_paint: bool) -> str:
    lines = [
        f'<image version="0.0.1" w="{export_data.width}" h="{export_data.height}">',
        '  <stack name="root">',
    ]
    # Topmost first
    for name in text_layers:
        lines.append(f'    <layer name="{name}" src="data/{name}.png" x="0" y="0" opacity="1.0" visibility="visible"/>')
    if include_paint:
        lines.append('    <layer name="Paint" src="data/paint.png" x="0" y="0" opacity="1.0" visibility="visible"/>')
    if include_mask:
        lines.append('    <layer name="Mask" src="data/mask.png" x="0" y="0" opacity="1.0" visibility="visible"/>')
    lines.append('    <layer name="Background" src="data/background.png" x="0" y="0" opacity="1.0" visibility="visible"/>')
    lines.append("  </stack>")
    lines.append("</image>")
    return "\n".join(lines)


def export_page_to_openraster(export_data: ExportPageData, output_path: Path) -> None:
    """Export the given page data to an OpenRaster (.ora) file."""
    temp_dir = Path(tempfile.mkdtemp(prefix="ora_export_"))
    try:
        data_dir = temp_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Background
        background_img = QtGui.QImage(str(export_data.background_image))
        _save_qimage(background_img, data_dir / "background.png")

        # Mask
        mask_included = False
        if export_data.mask_enabled:
            _create_mask_layer(export_data, data_dir / "mask.png")
            mask_included = True

        # Paint
        paint_included = _copy_or_save_paint_layer(export_data, data_dir / "paint.png")

        # Text layers
        text_layer_names: List[str] = []
        for idx, bubble in enumerate(export_data.bubbles, start=1):
            if not bubble.enabled or not export_data.text_enabled:
                continue
            if bubble.block_type == "sfx" and not export_data.show_sfx:
                continue
            layer_name = f"text_{idx}"
            _render_text_layer(export_data, bubble, data_dir / f"{layer_name}.png")
            text_layer_names.append(layer_name)

        stack_xml = _build_stack_xml(export_data, text_layer_names, mask_included, paint_included)

        with zipfile.ZipFile(output_path, "w") as zf:
            zf.writestr("mimetype", "image/openraster", compress_type=zipfile.ZIP_STORED)
            zf.writestr("stack.xml", stack_xml)
            zf.write(data_dir / "background.png", "data/background.png")
            if mask_included:
                zf.write(data_dir / "mask.png", "data/mask.png")
            if paint_included:
                zf.write(data_dir / "paint.png", "data/paint.png")
            for name in text_layer_names:
                zf.write(data_dir / f"{name}.png", f"data/{name}.png")
    finally:
        # Best-effort cleanup
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)
