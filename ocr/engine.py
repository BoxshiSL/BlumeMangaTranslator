"""EasyOCR wrapper for recognizing text on manga pages."""
from dataclasses import dataclass
from typing import List, Tuple

import easyocr
import numpy as np

from languages import get_ocr_langs_for_src


@dataclass
class OcrBlock:
    """OCR result for a single text fragment."""

    text: str
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2) in pixels
    confidence: float  # model confidence 0..1


class OcrEngine:
    """
    Wrapper around EasyOCR for manga/manhwa pages.

    Keeps an EasyOCR reader per source language and reinitializes if needed.
    """

    def __init__(self, src_lang: str = "ja", use_gpu: bool = False) -> None:
        self._use_gpu = use_gpu
        self._src_lang = (src_lang or "ja").lower()
        self._base_langs = get_ocr_langs_for_src(self._src_lang)
        self._reader = easyocr.Reader(self._base_langs, gpu=use_gpu)

    def _ensure_reader_for_lang(self, src_lang: str) -> None:
        """
        Recreate EasyOCR reader if source language changed.
        """
        src_lang = (src_lang or "").lower()
        if src_lang == self._src_lang:
            return

        self._src_lang = src_lang
        self._base_langs = get_ocr_langs_for_src(src_lang)
        self._reader = easyocr.Reader(self._base_langs, gpu=self._use_gpu)

    def recognize(self, image: np.ndarray, src_lang: str | None = None) -> List[OcrBlock]:
        """
        Recognize text on the provided image.

        :param image: NumPy array (H, W, C).
        :param src_lang: source language code (ja/ko/zh/en/...).
        :return: list of OcrBlock with text, bbox, confidence.
        """
        if not isinstance(image, np.ndarray):
            raise TypeError("image must be a numpy.ndarray")

        if src_lang is not None:
            self._ensure_reader_for_lang(src_lang)

        results = self._reader.readtext(image, detail=1, paragraph=False)

        blocks: List[OcrBlock] = []
        for bbox_points, text, confidence in results:
            xs = [p[0] for p in bbox_points]
            ys = [p[1] for p in bbox_points]
            x1, y1 = int(min(xs)), int(min(ys))
            x2, y2 = int(max(xs)), int(max(ys))
            blocks.append(
                OcrBlock(
                    text=text,
                    bbox=(x1, y1, x2, y2),
                    confidence=float(confidence),
                )
            )

        return blocks

    def recognize_to_dicts(self, image: np.ndarray, src_lang: str) -> list[dict]:
        """Helper to return OCR results as list of dicts for serialization/debug."""
        return [vars(block) for block in self.recognize(image, src_lang)]

