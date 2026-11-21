"""Subtitle cleanup and bounded, non-truncating line wrapping."""
from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Callable

MAX_SUBTITLE_LINES = 2
MAX_SUBTITLE_CHARS_PER_LINE = 42

_SCENE_LABEL_PATTERNS = (
    re.compile(r"^\s*\[\s*(?:(?:sahne|scene)\s*)?#?\s*\d+\s*\]\s*[:.)\-–—]?\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:sahne|scene)\s*#?\s*\d+\s*[:.)\-–—]\s*", re.IGNORECASE),
    re.compile(r"^\s*(?:sahne|scene)\s*#?\s*\d+\s+", re.IGNORECASE),
    re.compile(r"^\s*\d+\s*[.):\-–—]\s+"),
)


class SubtitleFitError(ValueError):
    """Subtitle text cannot fit the configured line count and width."""


def _strip_scene_label(line: str) -> str:
    cleaned = line.strip()
    for _ in range(2):
        previous = cleaned
        for pattern in _SCENE_LABEL_PATTERNS:
            cleaned = pattern.sub("", cleaned, count=1).strip()
            if cleaned != previous:
                break
        if cleaned == previous:
            break
    return cleaned


def clean_subtitle_block(
    text: str,
    *,
    max_lines: int = MAX_SUBTITLE_LINES,
    max_chars_per_line: int | None = MAX_SUBTITLE_CHARS_PER_LINE,
    max_width_px: float | None = None,
    measure_text: Callable[[str], float] | None = None,
) -> str:
    """Normalize labels/spacing and wrap at word boundaries without losing text.

    By default each line is limited to ``max_chars_per_line`` characters. A
    renderer may instead provide ``max_width_px`` and ``measure_text`` to wrap
    against the actual font metrics. If the text needs another line or has an
    unbreakable token that exceeds the selected limit, raise ``SubtitleFitError``
    instead of silently clipping or truncating it.
    """
    if max_lines < 1:
        raise ValueError("max_lines must be positive")
    if max_chars_per_line is not None and max_chars_per_line < 1:
        raise ValueError("max_chars_per_line must be positive or None")
    if max_chars_per_line is None and max_width_px is None:
        raise ValueError("a character or pixel width limit is required")
    if max_width_px is not None:
        try:
            max_width_px = float(max_width_px)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_width_px must be a positive finite number") from exc
        if not math.isfinite(max_width_px) or max_width_px <= 0 or measure_text is None:
            raise ValueError("pixel wrapping requires a positive width and measure_text callback")
    elif measure_text is not None:
        raise ValueError("measure_text requires max_width_px")

    def line_fits(line: str) -> bool:
        if max_chars_per_line is not None and len(line) > max_chars_per_line:
            return False
        if max_width_px is not None:
            try:
                measured = float(measure_text(line))  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                raise SubtitleFitError("subtitle font measurement failed") from exc
            if not math.isfinite(measured) or measured > max_width_px:
                return False
        return True

    normalized = unicodedata.normalize("NFC", str(text or "").replace("\r\n", "\n").replace("\r", "\n"))
    wrapped: list[str] = []
    for paragraph in normalized.split("\n"):
        paragraph = _strip_scene_label(paragraph)
        if not paragraph:
            continue
        current = ""
        for word in paragraph.split():
            if not line_fits(word):
                limit = (
                    f"{max_chars_per_line} characters"
                    if max_width_px is None else f"{max_width_px:g} pixels"
                )
                raise SubtitleFitError(f"subtitle token exceeds the line limit ({limit})")
            candidate = f"{current} {word}" if current else word
            if line_fits(candidate):
                current = candidate
                continue
            if current:
                wrapped.append(current)
            current = word
            if len(wrapped) >= max_lines:
                raise SubtitleFitError(f"subtitle needs more than {max_lines} lines")
        if current:
            wrapped.append(current)
        if len(wrapped) > max_lines:
            raise SubtitleFitError(f"subtitle needs more than {max_lines} lines")
    if not wrapped:
        raise SubtitleFitError("subtitle block is empty after scene-label cleanup")
    if len(wrapped) > max_lines:
        raise SubtitleFitError(f"subtitle needs more than {max_lines} lines")
    return "\n".join(wrapped)
