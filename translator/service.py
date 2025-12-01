"""Translation service orchestrating batching, context and glossary application."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

from config import get_knowledge_base_dir
from knowledge.context_manager import ContextEntry, ContextManager
from knowledge.loader import load_title_knowledge
from knowledge.models import TitleKnowledge, TitleMeta
from project.models import TitleProject
from project.page_session import TextBlock
from translator.base import (
    TranslationError,
    TranslationRequest,
    TranslationResult,
    TranslatorCapabilities,
    Translator,
)
from translator.errors import LimitedModeError
from translator.rate_limiter import (
    activate_slow_mode,
    get_backoff_state,
)
from translator.registry import create_translator, normalize_translator_id

_T = TypeVar("_T")


def _state_cache_key(engine_id: str, engine_state: Optional[Dict[str, Any]]) -> Tuple[str, Tuple[Tuple[str, Any], ...]]:
    normalized = normalize_translator_id(engine_id)
    items = tuple(sorted((engine_state or {}).items()))
    return normalized, items


def _fallback_knowledge(project: TitleProject) -> TitleKnowledge:
    meta = TitleMeta(
        id=project.title_id,
        display_name=project.title_name,
        original_language=project.original_language,
        target_language=project.target_language,
        editor_preferences=None,
        description=None,
        notes=None,
    )
    return TitleKnowledge(meta=meta, characters=[], terms=[], style=None)


def _apply_glossary_and_name_fixes(translated: str, knowledge: TitleKnowledge) -> str:
    result = translated
    for term in knowledge.terms:
        if term.source and term.target:
            result = result.replace(term.source, term.target)
    for character in knowledge.characters:
        if not character.display_name:
            continue
        for orig_name in character.original_names or []:
            if orig_name:
                result = result.replace(orig_name, character.display_name)
    return result


def _build_prompt_payload(
    text: str,
    project: TitleProject,
    knowledge: TitleKnowledge,
    context: Sequence[ContextEntry],
    src_lang: str,
    dst_lang: str,
) -> Dict[str, Any]:
    characters_data = [
        {
            "id": c.id,
            "display_name": c.display_name,
            "original_names": c.original_names,
            "gender": c.gender,
            "role": c.role,
            "pronouns": c.pronouns,
            "speech_style": c.speech_style,
        }
        for c in knowledge.characters
    ]
    terms_data = [
        {
            "source": t.source,
            "target": t.target,
            "term_type": t.term_type,
            "notes": t.notes,
            "tags": t.tags,
        }
        for t in knowledge.terms
    ]
    context_data = [{"original": e.original, "translated": e.translated} for e in context]

    return {
        "text": text,
        "src_lang": src_lang,
        "dst_lang": dst_lang,
        "title_id": knowledge.meta.id,
        "title_name": knowledge.meta.display_name,
        "style": {
            "tone": knowledge.style.tone if knowledge.style else None,
            "honorifics_policy": knowledge.style.honorifics_policy if knowledge.style else None,
            "sfx_policy": knowledge.style.sfx_policy if knowledge.style else None,
            "punctuation_style": knowledge.style.punctuation_style if knowledge.style else None,
            "casing_style": knowledge.style.casing_style if knowledge.style else None,
            "extra": knowledge.style.extra if knowledge.style else {},
        },
        "characters": characters_data,
        "terms": terms_data,
        "recent_context": context_data,
        "content_type": project.content_type,
        "color_mode": project.color_mode,
    }


class TranslationService:
    """Coordinates translator creation, batching and context-aware post-processing."""

    def __init__(self, ctx_manager: Optional[ContextManager] = None) -> None:
        self.ctx_manager = ctx_manager or ContextManager()
        self._translator_cache: Dict[Tuple[str, Tuple[Tuple[str, Any], ...]], Any] = {}
        self._rate_limit_callback: Optional[Callable[[str], None]] = None

    def set_rate_limit_callback(self, callback: Callable[[str], None]) -> None:
        """Register a callback to be notified when slow mode is activated for an engine."""
        self._rate_limit_callback = callback

    # -------------------- public API --------------------
    def translate_text(
        self,
        text: str,
        project: TitleProject,
        engine_id: str,
        engine_state: Optional[Dict[str, Any]] = None,
        src_lang: Optional[str] = None,
        dst_lang: Optional[str] = None,
        reset_context: bool = False,
    ) -> str:
        """Translate a single piece of text with knowledge/context awareness."""
        if not text or text.strip() == "":
            return text

        if reset_context:
            self.ctx_manager.clear()

        normalized_id = normalize_translator_id(engine_id)
        translator = self._get_translator(normalized_id, engine_state)
        knowledge = self._ensure_knowledge_loaded(project)
        src = (src_lang or project.original_language).lower()
        dst = (dst_lang or project.target_language).lower()

        context_limit = translator.capabilities.context_window or 10
        context = self.ctx_manager.get_recent_context(limit=context_limit)
        prompt_data = _build_prompt_payload(text, project, knowledge, context, src, dst)
        request = TranslationRequest(
            text=text,
            src_lang=src,
            dst_lang=dst,
            context=context,
            prompt_data=prompt_data,
        )
        result = self._run_with_rate_limit_retry(
            normalized_id, lambda: translator.translate_text(request)
        )
        translated = _apply_glossary_and_name_fixes(result.translated_text, knowledge)
        if translated:
            self.ctx_manager.add_segment(original=text, translated=translated)
        return translated

    def translate_blocks(
        self,
        blocks: Sequence[TextBlock],
        project: TitleProject,
        engine_id: str,
        engine_state: Optional[Dict[str, Any]] = None,
        src_lang: Optional[str] = None,
        dst_lang: Optional[str] = None,
        reset_context: bool = False,
    ) -> List[TextBlock]:
        """Translate a list of TextBlock instances in order."""
        if reset_context:
            self.ctx_manager.clear()

        normalized_id = normalize_translator_id(engine_id)
        translator = self._get_translator(normalized_id, engine_state)
        knowledge = self._ensure_knowledge_loaded(project)
        src = (src_lang or project.original_language).lower()
        dst = (dst_lang or project.target_language).lower()
        context_limit = translator.capabilities.context_window or 10

        request_pairs: List[Tuple[TextBlock, TranslationRequest]] = []
        for block in blocks:
            text = block.original_text or ""
            if not text.strip():
                block.translated_text = ""
                continue

            context = self.ctx_manager.get_recent_context(limit=context_limit)
            prompt_data = _build_prompt_payload(text, project, knowledge, context, src, dst)
            req = TranslationRequest(
                text=text,
                src_lang=src,
                dst_lang=dst,
                context=context,
                prompt_data=prompt_data,
                metadata={"block_id": block.id, "block_type": block.block_type},
            )
            request_pairs.append((block, req))

        requests = [req for _, req in request_pairs]
        if not requests:
            return list(blocks)

        batches = self._split_into_batches(requests, translator.capabilities)
        all_results: List[TranslationResult] = []
        for batch in batches:
            batch_results = self._run_with_rate_limit_retry(
                normalized_id, lambda b=batch: translator.translate_batch(b)
            )
            all_results.extend(batch_results)

        if len(all_results) != len(request_pairs):
            raise TranslationError("Translator returned unexpected number of results")

        for (block, req), res in zip(request_pairs, all_results):
            fixed = _apply_glossary_and_name_fixes(res.translated_text, knowledge)
            block.translated_text = fixed
            if fixed:
                self.ctx_manager.add_segment(original=req.text, translated=fixed)

        return list(blocks)

    # -------------------- helpers --------------------
    def _get_translator(self, engine_id: str, engine_state: Optional[Dict[str, Any]]) -> Translator:
        cache_key = _state_cache_key(engine_id, engine_state)
        translator = self._translator_cache.get(cache_key)
        if translator is not None:
            return translator

        translator = create_translator(engine_id, engine_state or {})
        self._translator_cache = {cache_key: translator}
        return translator

    def _ensure_knowledge_loaded(self, project: TitleProject) -> TitleKnowledge:
        if project.knowledge is not None:
            return project.knowledge
        try:
            base_dir = get_knowledge_base_dir()
            project.knowledge = load_title_knowledge(project.title_id, base_dir)
        except Exception:
            project.knowledge = _fallback_knowledge(project)
        return project.knowledge

    def _split_into_batches(
        self,
        requests: Sequence[TranslationRequest],
        capabilities: TranslatorCapabilities,
    ) -> List[List[TranslationRequest]]:
        if not capabilities.supports_batch:
            return [[req] for req in requests]

        max_batch = max(1, capabilities.max_batch_size or 1)
        max_chars = capabilities.max_chars_per_request

        batches: List[List[TranslationRequest]] = []
        current: List[TranslationRequest] = []
        current_chars = 0

        for req in requests:
            req_len = len(req.text or "")
            fits_count = len(current) < max_batch
            fits_chars = max_chars is None or (current_chars + req_len) <= max_chars

            if current and (not fits_count or not fits_chars):
                batches.append(current)
                current = []
                current_chars = 0

            current.append(req)
            current_chars += req_len

        if current:
            batches.append(current)

        return batches

    # -------------------- rate limit handling --------------------
    def _run_with_rate_limit_retry(self, engine_id: str, fn: Callable[[], _T]) -> _T:
        """Retry once in slow mode when a LimitedModeError is encountered."""
        try:
            return fn()
        except LimitedModeError as exc:
            activate_slow_mode(engine_id, str(exc))
            if self._rate_limit_callback:
                self._rate_limit_callback(engine_id)

            wait_for = max(get_backoff_state(engine_id).penalty_delay_sec, 1.5)
            time.sleep(wait_for)
            try:
                return fn()
            except LimitedModeError as exc2:
                raise TranslationError(str(exc2)) from exc2
