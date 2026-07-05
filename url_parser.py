from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import unquote, urlsplit


IMAGE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}

MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\((?P<url>https?://[^)\s]+)\)")
URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
TRAILING_PUNCTUATION = ".,!?;:，。！？；：、"


class SegmentKind(str, Enum):
    TEXT = "text"
    IMAGE_URL = "image_url"


@dataclass(frozen=True)
class ParsedSegment:
    kind: SegmentKind
    value: str


def split_image_urls(text: str) -> list[ParsedSegment]:
    """Split text into normal text and image URL segments."""
    segments: list[ParsedSegment] = []
    cursor = 0

    for match in _iter_image_url_matches(text):
        start, end, url = match
        if start > cursor:
            _append_text(segments, text[cursor:start])
        segments.append(ParsedSegment(SegmentKind.IMAGE_URL, url))
        cursor = end

    if cursor < len(text):
        _append_text(segments, text[cursor:])

    return segments


def _iter_image_url_matches(text: str):
    matches: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []

    for match in MARKDOWN_IMAGE_RE.finditer(text):
        url = _strip_trailing_punctuation(match.group("url"))
        occupied.append(match.span())
        matches.append((match.start(), match.end(), url))

    for match in URL_RE.finditer(text):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        raw_url = _strip_trailing_punctuation(match.group(0))
        if _looks_like_image_url(raw_url):
            matches.append((match.start(), match.start() + len(raw_url), raw_url))

    yield from sorted(matches, key=lambda item: item[0])


def _looks_like_image_url(url: str) -> bool:
    path = unquote(urlsplit(url).path).lower()
    return any(path.endswith(ext) for ext in IMAGE_EXTENSIONS)


def _strip_trailing_punctuation(url: str) -> str:
    return url.rstrip(TRAILING_PUNCTUATION)


def _append_text(segments: list[ParsedSegment], text: str) -> None:
    if not text:
        return
    if segments and segments[-1].kind == SegmentKind.TEXT:
        previous = segments[-1]
        segments[-1] = ParsedSegment(SegmentKind.TEXT, previous.value + text)
        return
    segments.append(ParsedSegment(SegmentKind.TEXT, text))
