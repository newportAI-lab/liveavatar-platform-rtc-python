from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any

# ── Markdown Stripping ───────────────────────────────────────

_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_UNORDERED_LIST_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_BLOCKQUOTE_RE = re.compile(r"^>\s*", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$", re.MULTILINE)
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_UNCLOSED_FENCE_RE = re.compile(r"```.*", re.DOTALL)


def strip_markdown(text: str) -> str:
    """Remove common Markdown formatting, keeping readable text."""
    # 1. Strip complete fenced code blocks, then drop trailing unclosed fences
    text = _FENCE_RE.sub("", text)
    text = _UNCLOSED_FENCE_RE.sub("", text)

    # 2. Remove table rows
    text = _TABLE_ROW_RE.sub("", text)
    text = _TABLE_SEP_RE.sub("", text)

    # 3. Images before links (images have ! prefix)
    text = _IMAGE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)

    # 4. Bold before italic
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)

    # 5. Inline code
    text = _INLINE_CODE_RE.sub(r"\1", text)

    # 6. Headings, list markers, blockquotes
    text = _HEADING_RE.sub("", text)
    text = _NUMBERED_LIST_RE.sub("", text)
    text = _UNORDERED_LIST_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)

    # 7. Collapse 3+ newlines into double newline (preserve paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text


# ── Text Normalization ───────────────────────────────────────

_URL_RE = re.compile(r"https?://\S+")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)%")
_NUMBER_RE = re.compile(r"\d+")


def normalize_text(text: str) -> str:
    """Basic text normalization for TTS: sanitize URLs/emails, expand percents and numbers."""
    text = _URL_RE.sub(" link ", text)
    text = _EMAIL_RE.sub(" email ", text)

    text = _PERCENT_RE.sub(r"\1 percent", text)

    def _replace_num(m: re.Match[str]) -> str:
        n = int(m.group(0))
        if n <= 99999999:
            return _spell_number(n)
        return m.group(0)

    text = _NUMBER_RE.sub(_replace_num, text)

    return text


def _spell_number(n: int) -> str:
    """Spell a non-negative integer in words (English)."""
    if n == 0:
        return "zero"
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n - 10]
    if n < 100:
        tens = _TENS[n // 10]
        ones = n % 10
        return tens if ones == 0 else f"{tens} {_ONES[ones]}"
    if n < 1000:
        hundreds = _ONES[n // 100]
        rest = n % 100
        return f"{hundreds} hundred {_spell_number(rest)}" if rest else f"{hundreds} hundred"
    if n < 1000000:
        thousands = _spell_number(n // 1000)
        rest = n % 1000
        return f"{thousands} thousand {_spell_number(rest)}" if rest else f"{thousands} thousand"
    if n < 100000000:
        millions = _spell_number(n // 1000000)
        rest = n % 1000000
        return f"{millions} million {_spell_number(rest)}" if rest else f"{millions} million"
    return str(n)


_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
          "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


# ── Sentence Boundary Detection ──────────────────────────────

_HARD_TERMINATORS = frozenset({".", "!", "?"})


def _is_sentence_period(text: str, pos: int) -> bool:
    """Check whether '.' at *pos* ends a sentence (not an abbreviation)."""
    if pos + 1 >= len(text):
        return True
    after = text[pos + 1]
    if after not in (" ", "\n", "\r", "\t"):
        return False
    # walk whitespace to next non-whitespace char
    j = pos + 1
    while j < len(text) and text[j] in (" ", "\t", "\r"):
        j += 1
    if j >= len(text):
        return True
    return text[j].isupper() or text[j] == "\n"


def _find_last_hard_boundary(text: str) -> int:
    """Index of the last hard sentence terminator, or -1."""
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch in _HARD_TERMINATORS:
            return i
        # Double newline (paragraph boundary)
        if ch == "\n" and i > 0 and text[i - 1] == "\n":
            if i < 2 or text[i - 2] != "\n":
                return i
    return -1


def _find_last_soft_boundary(text: str, soft_terminators: frozenset[str]) -> int:
    """Last soft terminator index (comma/semicolon fallback), or -1."""
    for i in range(len(text) - 1, -1, -1):
        if text[i] in soft_terminators:
            return i
    return -1


# ── TextChunker ──────────────────────────────────────────────

_DEFAULT_HARD_TERMINATORS = frozenset({".", "!", "?", "\n\n"})
_DEFAULT_SOFT_TERMINATORS = frozenset({",", ":", ";"})


class TextChunker:
    """Accumulates LLM SSE text chunks and flushes complete sentences for TTS.

    Parameters
    ----------
    max_chars:
        Flush at the last soft terminator when the buffer exceeds this length (default 150).
    max_time_ms:
        Flush any remaining buffer text after this many milliseconds of silence (default 500).
    hard_terminators:
        Characters that trigger an immediate sentence flush.
    soft_terminators:
        Characters used as fallback split points when *max_chars* triggers.
    on_flush:
        Callback invoked with each complete normalized sentence.
    loop:
        Event loop for the max-time timer. Uses ``asyncio.get_running_loop()`` by default.
    """

    def __init__(
        self,
        max_chars: int = 150,
        max_time_ms: int = 500,
        hard_terminators: frozenset[str] = _DEFAULT_HARD_TERMINATORS,
        soft_terminators: frozenset[str] = _DEFAULT_SOFT_TERMINATORS,
        on_flush: Callable[[str], Any] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.max_chars = max_chars
        self.max_time_ms = max_time_ms
        self.hard_terminators = hard_terminators
        self.soft_terminators = soft_terminators
        self.on_flush = on_flush

        self._buffer = ""
        self._timer_task: asyncio.Task[Any] | None = None
        self._loop = loop
        self._backpressure = False

    # ── Public API ────────────────────────────────────────────

    @property
    def buffer(self) -> str:
        """Current accumulated (un-flushed) text."""
        return self._buffer

    @property
    def backpressure(self) -> bool:
        """When True the chunker is under backpressure and should slow down."""
        return self._backpressure

    @backpressure.setter
    def backpressure(self, value: bool) -> None:
        self._backpressure = value

    def process(self, chunk: str) -> None:
        """Ingest an SSE text chunk.  Flushes complete sentences via *on_flush*."""
        cleaned = strip_markdown(chunk)
        self._buffer += cleaned

        while True:
            idx = _find_last_hard_boundary(self._buffer)
            if idx == -1:
                break
            sentence = self._buffer[: idx + 1]
            self._buffer = self._buffer[idx + 1 :]
            self._emit(sentence)

        # max_chars fallback
        effective_max = self.max_chars * 2 if self._backpressure else self.max_chars
        while len(self._buffer) >= effective_max:
            soft_idx = _find_last_soft_boundary(self._buffer, self.soft_terminators)
            if soft_idx >= 0:
                sentence = self._buffer[: soft_idx + 1]
                self._buffer = self._buffer[soft_idx + 1 :]
                self._emit(sentence)
            else:
                # No soft terminator — force flush everything
                self._emit(self._buffer)
                self._buffer = ""

        self._reset_timer()

    def flush_remaining(self) -> None:
        """Flush any text left in the buffer.  Call when the LLM stream ends."""
        self._cancel_timer()
        if self._buffer.strip():
            self._emit(self._buffer)
            self._buffer = ""

    def close(self) -> None:
        """Cancel background timer.  Does NOT flush — call *flush_remaining* first."""
        self._cancel_timer()

    # ── Internals ─────────────────────────────────────────────

    def _emit(self, text: str) -> None:
        text = normalize_text(text)
        if self.on_flush is None:
            return
        result = self.on_flush(text)
        if asyncio.iscoroutine(result):
            try:
                loop = self._loop or asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(result)

    def _reset_timer(self) -> None:
        self._cancel_timer()
        if self._buffer and self.max_time_ms > 0:
            try:
                loop = self._loop or asyncio.get_running_loop()
            except RuntimeError:
                return  # no running event loop — skip timer
            self._timer_task = loop.create_task(self._timer_callback())

    def _cancel_timer(self) -> None:
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    async def _timer_callback(self) -> None:
        await asyncio.sleep(self.max_time_ms / 1000.0)
        if self._buffer.strip():
            self._emit(self._buffer)
            self._buffer = ""
