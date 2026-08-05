# apps/api/tests/services/kb/test_chunking.py

"""Offset and structure invariants for knowledge-base markdown chunking."""

from itertools import pairwise
from unittest.mock import patch

import services.kb.chunking as chunking_module
from services.kb.chunking import chunk_markdown


def _fixture_markdown() -> str:
    overview = " ".join(
        f"Overview sentence {index} explains the workspace knowledge model." for index in range(14)
    )
    install = " ".join(
        f"Install sentence {index} keeps the procedure deterministic." for index in range(12)
    )
    return (
        "# Overview\n\n"
        f"{overview}\n\n"
        "```python\n"
        "def stable_example():\n"
        "    return 'the fenced block stays together'\n"
        "```\n\n"
        "## Install\n\n"
        f"{install}\n"
    )


def test_chunk_markdown_preserves_offsets_overlap_headings_and_fences() -> None:
    content = _fixture_markdown()
    chunks = chunk_markdown(
        content,
        target_tokens=80,
        max_tokens=100,
        overlap_tokens=10,
    )

    assert len(chunks) >= 3
    assert all(content[chunk.char_start : chunk.char_end] == chunk.content for chunk in chunks)
    assert all(chunk.token_estimate <= 100 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert any(chunk.heading_path == ("Overview",) for chunk in chunks)
    assert any(chunk.heading_path == ("Overview", "Install") for chunk in chunks)

    for previous, current in pairwise(chunks):
        assert current.char_start < previous.char_end
        assert previous.char_end - current.char_start <= 40

    fence_start = content.index("```python")
    fence_end = content.index("```", fence_start + 3) + 3
    boundaries = {boundary for chunk in chunks for boundary in (chunk.char_start, chunk.char_end)}
    assert not any(fence_start < boundary < fence_end for boundary in boundaries)


def test_chunk_markdown_splits_oversized_paragraph_on_sentence_boundaries() -> None:
    content = " ".join(f"Sentence {index} has bounded content." for index in range(40))

    chunks = chunk_markdown(
        content,
        target_tokens=30,
        max_tokens=36,
        overlap_tokens=4,
    )

    assert len(chunks) > 1
    assert all(content[chunk.char_start : chunk.char_end] == chunk.content for chunk in chunks)
    assert all(chunk.token_estimate <= 36 for chunk in chunks)
    assert all(
        chunk.content.rstrip().endswith(".") or chunk.char_end == len(content)
        for chunk in chunks[:-1]
    )


def test_chunk_markdown_hard_splits_boundary_free_runs() -> None:
    content = "x" * 401

    chunks = chunk_markdown(
        content,
        target_tokens=40,
        max_tokens=50,
        overlap_tokens=5,
    )

    assert len(chunks) == 3
    assert all(chunk.token_estimate <= 50 for chunk in chunks)
    assert all(content[chunk.char_start : chunk.char_end] == chunk.content for chunk in chunks)


def test_chunk_markdown_uses_fixed_character_heuristic_for_non_ascii_text() -> None:
    content = "漢" * 33

    chunks = chunk_markdown(
        content,
        target_tokens=3,
        max_tokens=4,
        overlap_tokens=0,
    )

    assert [len(chunk.content) for chunk in chunks] == [16, 16, 1]
    assert [chunk.token_estimate for chunk in chunks] == [4, 4, 0]


def test_chunk_markdown_is_deterministic_and_empty_safe() -> None:
    content = _fixture_markdown()
    kwargs = {
        "target_tokens": 80,
        "max_tokens": 100,
        "overlap_tokens": 10,
    }

    assert chunk_markdown(content, **kwargs) == chunk_markdown(content, **kwargs)
    assert (
        chunk_markdown(
            " \n\t",
            target_tokens=80,
            max_tokens=100,
            overlap_tokens=10,
        )
        == []
    )


def test_dense_markdown_fence_lookups_scale_linearly() -> None:
    def count_fence_lookups(size_bytes: int) -> tuple[int, int]:
        content = ("x\n\n" * ((size_bytes // 3) + 1))[:size_bytes]
        lookup_count = 0
        bisect_left = chunking_module.bisect_left

        def counted_bisect_left(values: list[int], offset: int) -> int:
            nonlocal lookup_count
            lookup_count += 1
            return bisect_left(values, offset)

        with patch.object(chunking_module, "bisect_left", counted_bisect_left):
            chunks = chunk_markdown(
                content,
                target_tokens=128,
                max_tokens=160,
                overlap_tokens=16,
            )
        return lookup_count, len(chunks)

    small_lookups, small_chunks = count_fence_lookups(512 * 1024)
    large_lookups, large_chunks = count_fence_lookups(1024 * 1024)

    assert small_lookups == small_chunks - 1
    assert large_lookups == large_chunks - 1
    assert large_lookups <= (small_lookups * 2) + 2
