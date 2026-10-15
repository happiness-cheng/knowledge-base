"""按真实 tokenizer 核验完整 embedding 输入，正文不静默截断。"""
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EmbeddingChunk:
    heading: str
    content: str
    embedding_text: str
    token_count: int
    header_shortened: bool


def count_tokens(tokenizer: Any, text: str) -> int:
    if tokenizer is None:
        raise ValueError('embedding tokenizer unavailable')
    return len(tokenizer(text, add_special_tokens=True, truncation=False)['input_ids'])


def _prefix(text: str, fits: Callable[[str], bool]) -> str:
    """每个候选都实际计数；无需依赖 tokenizer 严格单调才能保证输出合法。"""
    low, high, best = 1, len(text), 0
    while low <= high:
        middle = (low + high) // 2
        if fits(text[:middle]):
            best, low = middle, middle + 1
        else:
            high = middle - 1
    return text[:best]


def _token_prefix(text: str, tokenizer: Any, limit: int, *, header: str = '') -> str:
    def fits(candidate: str) -> bool:
        return count_tokens(tokenizer, header + candidate) <= limit
    return _prefix(text, fits)


def prepare_chunks(chunks: Iterable[tuple[str, str]], title: str, tokenizer: Any,
                   *, max_tokens: int = 512) -> list[EmbeddingChunk]:
    chunks = list(chunks)
    if not chunks:
        return []
    if tokenizer is None:
        raise ValueError('embedding tokenizer unavailable')
    if type(max_tokens) is not int or max_tokens < 8:
        raise ValueError('invalid embedding budget')
    prepared = []
    for heading, content in chunks:
        original_header = f'{title}\n{heading}\n' if title else f'{heading}\n'
        header = original_header
        header_limit = min(96, max_tokens - 4)
        if count_tokens(tokenizer, header) > header_limit:
            short_title = _token_prefix(title, tokenizer, min(64, header_limit // 2))
            short_heading = _token_prefix(heading, tokenizer, min(24, header_limit // 4))
            header = f'{short_title}\n{short_heading}\n' if short_title else f'{short_heading}\n'
            header = _token_prefix(header, tokenizer, header_limit)
        shortened = header != original_header
        remaining = content
        while remaining:
            full = header + remaining
            if count_tokens(tokenizer, full) <= max_tokens:
                piece = remaining
            else:
                piece = _token_prefix(remaining, tokenizer, max_tokens, header=header)
            if not piece:
                raise ValueError('embedding body cannot fit budget')
            prepared.append(EmbeddingChunk(heading, piece, header + piece,
                                           count_tokens(tokenizer, header + piece), shortened))
            remaining = remaining[len(piece):]
    return prepared
