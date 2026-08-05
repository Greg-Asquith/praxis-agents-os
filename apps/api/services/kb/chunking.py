# apps/api/services/kb/chunking.py

"""Deterministic, offset-preserving markdown chunking."""

import re
from bisect import bisect_left
from dataclasses import dataclass

from services.kb.domain import ChunkDraft
from utils.tokens import estimate_tokens_by_character_count as estimate_tokens

_ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*(?:\r?\n)?$")
_FENCE_RE = re.compile(r"^[ \t]*```")
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])(?:[ \t]+|\r?\n+)|\r?\n+")


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    heading_path: tuple[str, ...]
    is_fence: bool = False


def _line_ranges(content: str) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    offset = 0
    for line in content.splitlines(keepends=True):
        end = offset + len(line)
        ranges.append((offset, end, line))
        offset = end
    if offset < len(content):
        ranges.append((offset, len(content), content[offset:]))
    return ranges


def _scan_blocks(content: str) -> list[_Block]:
    lines = _line_ranges(content)
    blocks: list[_Block] = []
    headings: list[str] = []
    index = 0

    while index < len(lines):
        start, end, line = lines[index]
        if not line.strip():
            index += 1
            continue

        heading_match = _ATX_HEADING_RE.match(line)
        is_fence = bool(_FENCE_RE.match(line))

        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            headings = headings[: level - 1]
            headings.append(title)
            index += 1
        elif is_fence:
            marker = line.lstrip()[:3]
            index += 1
            while index < len(lines):
                _, end, candidate = lines[index]
                index += 1
                if candidate.lstrip().startswith(marker):
                    break
        else:
            index += 1
            while index < len(lines):
                _, next_end, candidate = lines[index]
                if (
                    not candidate.strip()
                    or _ATX_HEADING_RE.match(candidate)
                    or _FENCE_RE.match(candidate)
                ):
                    break
                end = next_end
                index += 1

        while index < len(lines) and not lines[index][2].strip():
            end = lines[index][1]
            index += 1

        blocks.append(
            _Block(
                start=start,
                end=end,
                heading_path=tuple(headings),
                is_fence=is_fence,
            )
        )

    return blocks


def _split_block(content: str, block: _Block, max_chars: int) -> list[_Block]:
    if block.end - block.start <= max_chars:
        return [block]

    pieces: list[_Block] = []
    start = block.start
    while block.end - start > max_chars:
        hard_end = start + max_chars
        split_at = hard_end
        if not block.is_fence:
            window = content[start:hard_end]
            boundaries = list(_SENTENCE_BOUNDARY_RE.finditer(window))
            if boundaries:
                candidate = start + boundaries[-1].end()
                if candidate > start:
                    split_at = candidate
        pieces.append(
            _Block(
                start=start,
                end=split_at,
                heading_path=block.heading_path,
                is_fence=block.is_fence,
            )
        )
        start = split_at
    if start < block.end:
        pieces.append(
            _Block(
                start=start,
                end=block.end,
                heading_path=block.heading_path,
                is_fence=block.is_fence,
            )
        )
    return pieces


def _fit_start_to_token_limit(
    content: str,
    *,
    start: int,
    end: int,
    max_tokens: int,
) -> int:
    if estimate_tokens(content[start:end]) <= max_tokens:
        return start
    low = start
    high = end
    while low < high:
        midpoint = (low + high) // 2
        if estimate_tokens(content[midpoint:end]) <= max_tokens:
            high = midpoint
        else:
            low = midpoint + 1
    return low


def _overlap_start(
    content: str,
    *,
    previous_start: int,
    previous_end: int,
    current_end: int,
    overlap_tokens: int,
    max_tokens: int,
) -> int:
    overlap_chars = overlap_tokens * 4
    if overlap_chars <= 0:
        return previous_end

    hard_floor = max(previous_start, current_end - (max_tokens * 4))
    desired_floor = max(previous_start, previous_end - overlap_chars, hard_floor)
    desired_floor = _fit_start_to_token_limit(
        content,
        start=desired_floor,
        end=previous_end,
        max_tokens=overlap_tokens,
    )
    desired_floor = _fit_start_to_token_limit(
        content,
        start=desired_floor,
        end=current_end,
        max_tokens=max_tokens,
    )
    if desired_floor >= previous_end:
        return previous_end

    window = content[desired_floor:previous_end]
    boundary = _SENTENCE_BOUNDARY_RE.search(window)
    if boundary and desired_floor + boundary.end() < previous_end:
        return desired_floor + boundary.end()
    return desired_floor


def chunk_markdown(
    content_md: str,
    *,
    target_tokens: int,
    max_tokens: int,
    overlap_tokens: int,
) -> list[ChunkDraft]:
    """Split markdown into deterministic chunks while preserving exact offsets."""
    if not content_md.strip():
        return []
    if target_tokens <= 0 or max_tokens <= 0:
        raise ValueError("Chunk token limits must be positive")
    if target_tokens > max_tokens:
        raise ValueError("target_tokens must not exceed max_tokens")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be nonnegative and below target_tokens")

    max_chars = max_tokens * 4
    pieces = [
        piece
        for block in _scan_blocks(content_md)
        for piece in _split_block(content_md, block, max_chars)
    ]
    if not pieces:
        return []

    packed: list[tuple[int, int, tuple[str, ...]]] = []
    chunk_start = pieces[0].start
    chunk_end = pieces[0].end
    heading_path = pieces[0].heading_path

    for piece in pieces[1:]:
        candidate = content_md[chunk_start : piece.end]
        if estimate_tokens(candidate) <= target_tokens:
            chunk_end = piece.end
            continue
        packed.append((chunk_start, chunk_end, heading_path))
        chunk_start = piece.start
        chunk_end = piece.end
        heading_path = piece.heading_path
    packed.append((chunk_start, chunk_end, heading_path))

    fence_pieces = [piece for piece in pieces if piece.is_fence]
    fence_starts = [piece.start for piece in fence_pieces]
    drafts: list[ChunkDraft] = []
    previous_start: int | None = None
    previous_end: int | None = None
    for chunk_index, (natural_start, chunk_end, heading_path) in enumerate(packed):
        char_start = natural_start
        if previous_start is not None and previous_end is not None:
            char_start = _overlap_start(
                content_md,
                previous_start=previous_start,
                previous_end=previous_end,
                current_end=chunk_end,
                overlap_tokens=overlap_tokens,
                max_tokens=max_tokens,
            )
            fence_index = bisect_left(fence_starts, char_start) - 1
            if fence_index >= 0:
                fence = fence_pieces[fence_index]
                if char_start < fence.end:
                    with_fence = content_md[fence.start : chunk_end]
                    fence_overlap = content_md[fence.start : previous_end]
                    if (
                        estimate_tokens(with_fence) <= max_tokens
                        and estimate_tokens(fence_overlap) <= overlap_tokens
                    ):
                        char_start = fence.start
                    else:
                        char_start = fence.end
        chunk_content = content_md[char_start:chunk_end]
        drafts.append(
            ChunkDraft(
                chunk_index=chunk_index,
                content=chunk_content,
                char_start=char_start,
                char_end=chunk_end,
                token_estimate=estimate_tokens(chunk_content),
                heading_path=heading_path,
            )
        )
        previous_start = char_start
        previous_end = chunk_end

    return drafts
