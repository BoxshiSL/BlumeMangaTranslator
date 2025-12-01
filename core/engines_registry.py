"""Unified registry of OCR and translator engines with metadata and download links."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Sequence

from i18n import tr

EngineMode = Literal["offline", "cloud"]
EngineKind = Literal["ocr", "translator"]


@dataclass(frozen=True)
class EngineConfig:
    id: str
    kind: EngineKind
    mode: EngineMode
    name_key: str
    description_key: str
    estimated_size_mb: int | None
    download_urls: list[str]
    requires_api_key: bool
    requires_endpoint: bool = False
    api_optional: bool = False
    supports_api: bool = False
    supports_scrape_mode: bool = False

    @property
    def name(self) -> str:
        return tr(self.name_key)

    @property
    def description(self) -> str:
        return tr(self.description_key)


# Base folder for all downloaded models.
MODELS_BASE_DIR = Path(__file__).resolve().parent.parent / "models"


def get_engine_models_dir(engine: EngineConfig) -> Path:
    """Return a default directory for storing models of the given engine."""
    if engine.id == "tesseract":
        return MODELS_BASE_DIR / engine.kind / engine.id / "tessdata"
    return MODELS_BASE_DIR / engine.kind / engine.id


OCR_ENGINES: Sequence[EngineConfig] = (
    EngineConfig(
        id="easyocr",
        kind="ocr",
        mode="offline",
        name_key="ocr.easyocr.name",
        description_key="ocr.easyocr.description",
        estimated_size_mb=300,
        download_urls=[
            "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/craft_mlt_25k.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/chinese_sim.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/japanese.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/korean.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/pre-v1.1.6/latin.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/english_g2.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/zh_sim_g2.zip",
            "https://github.com/JaidedAI/EasyOCR/releases/download/v1.3/korean_g2.zip",
        ],
        requires_api_key=False,
    ),
    EngineConfig(
        id="paddleocr",
        kind="ocr",
        mode="offline",
        name_key="ocr.paddleocr.name",
        description_key="ocr.paddleocr.description",
        estimated_size_mb=400,
        download_urls=[
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/Multilingual_PP-OCRv3_det_infer.tar",
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/Multilingual_PP-OCRv3_rec_infer.tar",
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/japan_PP-OCRv3_rec_infer.tar",
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/multilingual/korean_PP-OCRv3_rec_infer.tar",
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/chinese/ch_PP-OCRv3_det_infer.tar",
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/chinese/ch_PP-OCRv3_rec_infer.tar",
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/english/en_PP-OCRv3_det_infer.tar",
            "https://paddleocr.bj.bcebos.com/PP-OCRv3/english/en_PP-OCRv3_rec_infer.tar",
        ],
        requires_api_key=False,
    ),
    EngineConfig(
        id="tesseract",
        kind="ocr",
        mode="offline",
        name_key="ocr.tesseract.name",
        description_key="ocr.tesseract.description",
        estimated_size_mb=250,
        download_urls=[
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata",
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/rus.traineddata",
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/jpn.traineddata",
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/kor.traineddata",
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/chi_sim.traineddata",
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/spa.traineddata",
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/deu.traineddata",
            "https://github.com/tesseract-ocr/tessdata_best/raw/main/ita.traineddata",
        ],
        requires_api_key=False,
    ),
    EngineConfig(
        id="google_vision",
        kind="ocr",
        mode="cloud",
        name_key="ocr.google_vision.name",
        description_key="ocr.google_vision.description",
        estimated_size_mb=None,
        download_urls=[],
        requires_api_key=True,
        supports_api=True,
    ),
    EngineConfig(
        id="azure",
        kind="ocr",
        mode="cloud",
        name_key="ocr.azure_cv.name",
        description_key="ocr.azure_cv.description",
        estimated_size_mb=None,
        download_urls=[],
        requires_api_key=True,
        requires_endpoint=True,
        supports_api=True,
    ),
)

TRANSLATOR_ENGINES: Sequence[EngineConfig] = (
    EngineConfig(
        id="deepl",
        kind="translator",
        mode="cloud",
        name_key="translator.deepl.name",
        description_key="translator.deepl.description",
        estimated_size_mb=None,
        download_urls=[],
        requires_api_key=True,
        api_optional=True,
        supports_api=True,
        supports_scrape_mode=True,
    ),
    EngineConfig(
        id="google_translate",
        kind="translator",
        mode="cloud",
        name_key="translator.google.name",
        description_key="translator.google.description",
        estimated_size_mb=None,
        download_urls=[],
        requires_api_key=True,
        api_optional=True,
        supports_api=True,
        supports_scrape_mode=True,
    ),
    EngineConfig(
        id="yandex_translate",
        kind="translator",
        mode="cloud",
        name_key="translator.yandex.name",
        description_key="translator.yandex.description",
        estimated_size_mb=None,
        download_urls=[],
        requires_api_key=True,
        api_optional=True,
        supports_api=True,
        supports_scrape_mode=True,
    ),
    EngineConfig(
        id="azure_translate",
        kind="translator",
        mode="cloud",
        name_key="translator.azure.name",
        description_key="translator.azure.description",
        estimated_size_mb=None,
        download_urls=[],
        requires_api_key=True,
        requires_endpoint=True,
        supports_api=True,
    ),
    EngineConfig(
        id="openai_translate",
        kind="translator",
        mode="cloud",
        name_key="translator.openai.name",
        description_key="translator.openai.description",
        estimated_size_mb=None,
        download_urls=[],
        requires_api_key=True,
        supports_api=True,
    ),
    EngineConfig(
        id="argos",
        kind="translator",
        mode="offline",
        name_key="translator.argos.name",
        description_key="translator.argos.description",
        estimated_size_mb=900,
        download_urls=[
            "https://data.argosopentech.com/argospm/v1/translate-en_ja-1_1.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-ja_en-1_1.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-en_zh-1_9.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-zh_en-1_9.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-en_ko-1_1.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-ko_en-1_1.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-en_es-1_9.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-es_en-1_9.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-en_de-1_0.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-de_en-1_0.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-en_ru-1_9.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-ru_en-1_9.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-en_it-1_0.argosmodel",
            "https://data.argosopentech.com/argospm/v1/translate-it_en-1_0.argosmodel",
        ],
        requires_api_key=False,
    ),
    EngineConfig(
        id="marian_m2m_nllb",
        kind="translator",
        mode="offline",
        name_key="translator.marian.name",
        description_key="translator.marian.description",
        estimated_size_mb=2000,
        download_urls=[
            "https://huggingface.co/facebook/m2m100_418M/resolve/main/pytorch_model.bin",
            "https://huggingface.co/facebook/m2m100_418M/resolve/main/config.json",
            "https://huggingface.co/facebook/m2m100_418M/resolve/main/tokenizer_config.json",
            "https://huggingface.co/facebook/m2m100_418M/resolve/main/source.spm",
            "https://huggingface.co/facebook/m2m100_418M/resolve/main/target.spm",
        ],
        requires_api_key=False,
    ),
)

ENGINE_BY_ID: Dict[str, EngineConfig] = {
    cfg.id: cfg for cfg in (*OCR_ENGINES, *TRANSLATOR_ENGINES)
}

ENGINE_ALIASES: Dict[str, str] = {
    "yandex": "yandex_translate",
    "openai": "openai_translate",
    "marianmt": "marian_m2m_nllb",
}


def normalize_engine_id(engine_id: str) -> str:
    """Return a normalized id accounting for legacy names."""
    return ENGINE_ALIASES.get(engine_id, engine_id)
