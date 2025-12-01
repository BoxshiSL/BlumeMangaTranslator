"""Core project models: pages and title-level project representation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PageInfo:
    """Metadata for a single page within a title project."""

    index: int  # global index within the title (0-based)
    file_path: Path  # path to the page image
    chapter_number: int = 1  # chapter number (1, 2, 3, ...)
    page_in_chapter: int = 0  # page number within the chapter
    ocr_done: bool = False  # whether OCR has been completed
    translation_done: bool = False  # whether draft translation has been completed
    session_path: Optional[Path] = None  # path to the saved session file, if any
    normalized_path: Optional[Path] = None  # cached path to normalized image


@dataclass
class TitleProject:
    """Represents an opened manga title project."""

    title_id: str  # internal identifier (usually folder name)
    title_name: str  # display name of the title
    folder_path: Path  # path to the title folder
    pages: list[PageInfo]  # ordered list of pages

    original_language: str  # source language code
    target_language: str  # target language code
    skip_sfx_by_default: bool = True  # do not translate SFX by default

    knowledge: Optional["TitleKnowledge"] = None  # title knowledge base, optional
    context_manager: Optional["ContextManager"] = None  # context manager, optional

    meta_path: Optional[Path] = None  # path to project.yaml if it exists
    content_type: str = "standard"  # "standard" | "adult"
    color_mode: str = "bw"  # "bw" | "color"
    target_width: int = 0
    target_height: int = 0
    resolution_preset_id: str = "custom"
    normalized_images_dir: Path = Path(".normalized")

    def get_page_count(self) -> int:
        """Return the number of pages in the project."""
        return len(self.pages)

    def get_page(self, index: int) -> PageInfo:
        """Return a page by index or raise IndexError if out of bounds."""
        if index < 0 or index >= len(self.pages):
            raise IndexError(f"Page index {index} out of range for project '{self.title_id}'")
        return self.pages[index]
