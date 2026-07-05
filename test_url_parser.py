from url_parser import SegmentKind, split_image_urls


def test_split_raw_image_url_at_end():
    segments = split_image_urls("看这个 https://example.com/cat.png")

    assert [(segment.kind, segment.value) for segment in segments] == [
        (SegmentKind.TEXT, "看这个 "),
        (SegmentKind.IMAGE_URL, "https://example.com/cat.png"),
    ]


def test_split_markdown_image_without_extension():
    segments = split_image_urls("图：![x](https://cdn.example.com/render?id=1) 完成")

    assert [(segment.kind, segment.value) for segment in segments] == [
        (SegmentKind.TEXT, "图："),
        (SegmentKind.IMAGE_URL, "https://cdn.example.com/render?id=1"),
        (SegmentKind.TEXT, " 完成"),
    ]


def test_keeps_non_image_url_as_text():
    segments = split_image_urls("文档 https://example.com/page.html")

    assert [(segment.kind, segment.value) for segment in segments] == [
        (SegmentKind.TEXT, "文档 https://example.com/page.html"),
    ]


def test_preserves_mixed_url_order():
    segments = split_image_urls(
        "A https://example.com/a.jpg B ![b](https://example.com/b) C"
    )

    assert [(segment.kind, segment.value) for segment in segments] == [
        (SegmentKind.TEXT, "A "),
        (SegmentKind.IMAGE_URL, "https://example.com/a.jpg"),
        (SegmentKind.TEXT, " B "),
        (SegmentKind.IMAGE_URL, "https://example.com/b"),
        (SegmentKind.TEXT, " C"),
    ]
