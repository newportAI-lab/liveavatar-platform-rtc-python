import asyncio

import pytest

from liveavatar_rtc.text_chunker import (
    TextChunker,
    _find_last_hard_boundary,
    _find_last_soft_boundary,
    _is_sentence_period,
    _spell_number,
    normalize_text,
    strip_markdown,
)


# ── Markdown Stripper ────────────────────────────────────────


class TestStripMarkdownFencedCode:
    def test_strips_single_fenced_block(self):
        text = "Before\n```python\nprint('hi')\n```\nAfter"
        result = strip_markdown(text)
        assert "print" not in result
        assert "Before" in result
        assert "After" in result

    def test_strips_multiple_fenced_blocks(self):
        text = "```a\nx\n```\nmid\n```b\ny\n```"
        result = strip_markdown(text)
        assert "x" not in result
        assert "y" not in result
        assert "mid" in result

    def test_unclosed_fence_drops_rest(self):
        text = "keep\n```\nlost"
        result = strip_markdown(text)
        assert "keep" in result
        assert "lost" not in result


class TestStripMarkdownInline:
    def test_strips_bold(self):
        assert strip_markdown("**hello** world") == "hello world"

    def test_strips_italic(self):
        assert strip_markdown("*hello* world") == "hello world"

    def test_strips_link_keeps_text(self):
        assert strip_markdown("[click](https://x.com)") == "click"

    def test_strips_image_keeps_alt(self):
        assert strip_markdown("![logo](img.png)") == "logo"

    def test_strips_inline_code(self):
        assert strip_markdown("use `func()` now") == "use func() now"


class TestStripMarkdownBlocks:
    def test_strips_headings(self):
        assert strip_markdown("# Title\n\ntext") == "Title\n\ntext"
        assert strip_markdown("### Deep\n\nbody") == "Deep\n\nbody"

    def test_strips_unordered_list_markers(self):
        assert strip_markdown("- item1\n- item2") == "item1\nitem2"

    def test_strips_ordered_list_markers(self):
        assert strip_markdown("1. first\n2. second") == "first\nsecond"

    def test_strips_blockquote(self):
        assert strip_markdown("> quoted") == "quoted"

    def test_strips_table_rows(self):
        text = "| a | b |\n|-----|\n| 1 | 2 |"
        result = strip_markdown(text)
        assert "a" not in result
        assert "1" not in result

    def test_collapses_excess_newlines(self):
        assert strip_markdown("a\n\n\n\nb") == "a\n\nb"


# ── Number Spelling ──────────────────────────────────────────


class TestSpellNumber:
    def test_zero(self):
        assert _spell_number(0) == "zero"

    def test_single_digit(self):
        assert _spell_number(3) == "three"
        assert _spell_number(9) == "nine"

    def test_ten(self):
        assert _spell_number(10) == "ten"

    def test_eleven(self):
        assert _spell_number(11) == "eleven"

    def test_twenty(self):
        assert _spell_number(20) == "twenty"

    def test_twenty_one(self):
        assert _spell_number(21) == "twenty one"

    def test_hundred(self):
        assert _spell_number(100) == "one hundred"

    def test_hundred_and_twenty(self):
        assert _spell_number(120) == "one hundred twenty"

    def test_thousand(self):
        assert _spell_number(2024) == "two thousand twenty four"

    def test_ten_thousand(self):
        assert _spell_number(50000) == "fifty thousand"


class TestNormalizeText:
    def test_url_replaced(self):
        assert normalize_text("see https://example.com/path now") == "see  link  now"

    def test_email_replaced(self):
        assert normalize_text("mail a@b.com pls") == "mail  email  pls"

    def test_percent(self):
        assert normalize_text("50% off") == "fifty percent off"

    def test_simple_number(self):
        assert normalize_text("I bought 3 apples") == "I bought three apples"

    def test_large_number(self):
        assert normalize_text("year 2024") == "year two thousand twenty four"


# ── Sentence Boundary Detection ──────────────────────────────


class TestIsSentencePeriod:
    def test_true_at_end_of_text(self):
        assert _is_sentence_period("end.", 3) is True

    def test_true_before_space_and_upper(self):
        assert _is_sentence_period("x. Next", 1) is True

    def test_true_before_newline(self):
        assert _is_sentence_period("x.\nNext", 1) is True

    def test_false_for_abbreviation_lowercase(self):
        # "e.g. something" — period + space + lowercase → not a sentence end
        assert _is_sentence_period("e.g. something", 3) is False

    def test_false_for_number(self):
        assert _is_sentence_period("3.14", 1) is False


class TestFindLastHardBoundary:
    def test_period(self):
        assert _find_last_hard_boundary("Hi. World") == 2

    def test_exclamation(self):
        assert _find_last_hard_boundary("Wow! Nice") == 3

    def test_double_newline(self):
        assert _find_last_hard_boundary("line\n\nnext") == 5

    def test_no_boundary(self):
        assert _find_last_hard_boundary("hello world") == -1

    def test_last_of_multiple(self):
        # Should return the LAST terminator
        idx = _find_last_hard_boundary("A. B. C")
        assert idx == 4  # position of second .


def test_find_last_soft_boundary():
    assert _find_last_soft_boundary("a,b,c", frozenset({",", ";"})) == 3
    assert _find_last_soft_boundary("abc", frozenset({",", ";"})) == -1


# ── TextChunker ──────────────────────────────────────────────


class TestTextChunkerBasic:
    def test_flushes_on_period(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("Hello.")
        assert sentences == ["Hello."]
        assert c.buffer == ""

    def test_accumulates_without_terminator(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("Based on current data,")
        assert sentences == []
        assert "Based" in c.buffer

    def test_flushes_complete_sentence_from_multi_chunk(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("Based on current")
        assert sentences == []
        c.process(" data, the market is volatile.")
        assert len(sentences) == 1
        assert "volatile" in sentences[0]

    def test_keeps_remnant_after_flush(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("It is volatile. We suggest watching")
        assert len(sentences) == 1
        assert sentences[0] == "It is volatile."
        assert c.buffer == " We suggest watching"


class TestTextChunkerMaxChars:
    def test_flushes_at_soft_boundary_on_max_chars(self):
        sentences: list[str] = []
        c = TextChunker(max_chars=20, on_flush=sentences.append)
        # Long text with commas but no sentence terminators
        long_text = "This is a very long sentence, with many commas, that goes on, and on, "
        c.process(long_text)
        assert len(sentences) >= 1
        for s in sentences:
            assert s.endswith(",")

    def test_force_flushes_with_no_soft_boundary(self):
        sentences: list[str] = []
        c = TextChunker(max_chars=10, on_flush=sentences.append)
        c.process("abcdefghijklmnop")
        assert len(sentences) >= 1

    def test_backpressure_doubles_effective_max_chars(self):
        sentences: list[str] = []
        c = TextChunker(max_chars=20, on_flush=sentences.append)
        c.backpressure = True
        # Under backpressure, effective max_chars = 40
        text = "Short text, another phrase, third phrase"
        c.process(text)
        assert len(text) < 40 or len(sentences) > 0


class TestTextChunkerFlushRemaining:
    def test_flushes_buffer_on_done(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("An unfinished sentence")
        assert sentences == []
        c.flush_remaining()
        assert len(sentences) == 1
        assert sentences[0] == "An unfinished sentence"

    def test_empty_buffer_noop(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.flush_remaining()
        assert sentences == []

    def test_whitespace_only_buffer_noop(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c._buffer = "   \n  "
        c.flush_remaining()
        assert sentences == []


class TestTextChunkerMultipleSentences:
    def test_flushes_multiple_sentences_in_one_chunk(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("First sentence. Second sentence! Third sentence?")
        # Last boundary is "?" — everything up to it flushed together
        assert sentences == ["First sentence. Second sentence! Third sentence?"]
        assert c.buffer == ""

    def test_english_mixed(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("I see. Next up! What now?")
        # Last boundary is "?" — all complete sentences flushed together
        assert len(sentences) == 1
        assert "I see. Next up! What now?" in sentences[0]

    def test_paragraph_boundary(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("Paragraph one\n\nParagraph two")
        assert sentences == ["Paragraph one\n\n"]
        assert c.buffer == "Paragraph two"


class TestTextChunkerMarkdownIntegration:
    def test_strips_code_before_splitting(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("Output: ```python\nprint('hi')\n```\nAbove is the code.")
        assert len(sentences) == 1
        assert "print" not in sentences[0]
        assert "Output" in sentences[0]
        assert "the code" in sentences[0]

    def test_strips_links(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("Click [here](https://x.com) to view.")
        assert sentences == ["Click here to view."]


class TestTextChunkerNormalizationIntegration:
    def test_normalizes_numbers(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("I bought 3 apples.")
        assert "three" in sentences[0]

    def test_normalizes_urls(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("Visit https://example.com.")
        assert "link" in sentences[0]
        assert "example.com" not in sentences[0]


class TestTextChunkerTimer:
    @pytest.mark.asyncio
    async def test_max_time_flushes_buffer(self):
        """After max_time_ms of silence, the buffer is force-flushed."""
        sentences: list[str] = []
        c = TextChunker(max_time_ms=100, on_flush=sentences.append)
        c.process("Not finished")
        assert sentences == []
        await asyncio.sleep(0.2)
        assert len(sentences) == 1
        assert sentences[0] == "Not finished"
        c.close()

    @pytest.mark.asyncio
    async def test_timer_resets_on_new_chunk(self):
        sentences: list[str] = []
        c = TextChunker(max_time_ms=200, on_flush=sentences.append)
        c.process("First part")
        await asyncio.sleep(0.1)
        c.process(" continues without punctuation")
        await asyncio.sleep(0.15)
        assert sentences == []
        await asyncio.sleep(0.15)
        assert len(sentences) == 1
        c.close()

    @pytest.mark.asyncio
    async def test_close_cancels_timer(self):
        sentences: list[str] = []
        c = TextChunker(max_time_ms=100, on_flush=sentences.append)
        c.process("test")
        c.close()
        await asyncio.sleep(0.15)
        assert sentences == []


class TestTextChunkerEdgeCases:
    def test_empty_chunk(self):
        c = TextChunker()
        c.process("")
        assert c.buffer == ""

    def test_only_whitespace(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("   \n  ")
        assert sentences == []

    def test_multiple_terminators_together(self):
        sentences: list[str] = []
        c = TextChunker(on_flush=sentences.append)
        c.process("What?!")
        assert len(sentences) >= 1

    def test_no_on_flush_does_not_crash(self):
        c = TextChunker()
        c.process("Hello.")
        assert c.buffer == ""

    def test_long_buffer_no_boundaries(self):
        sentences: list[str] = []
        c = TextChunker(max_chars=10, on_flush=sentences.append)
        c.process("abcdefghijklmno")
        assert len(sentences) >= 1

    @pytest.mark.asyncio
    async def test_concurrent_process_from_same_chunker(self):
        """Process calls from different async contexts should be safe."""
        sentences: list[str] = []
        c = TextChunker(max_time_ms=1000, on_flush=sentences.append)

        async def feed(chunks):
            for chunk in chunks:
                c.process(chunk)
                await asyncio.sleep(0)

        await asyncio.gather(
            feed(["Hello", " world. "]),
            feed(["Second", " sentence!"]),
        )
        c.flush_remaining()
        assert len(sentences) >= 1
        c.close()
