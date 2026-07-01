from src.agent.tools import lcl_insights_store as store


def test_slug_from_url_handles_trailing_slash() -> None:
    assert (
        store.slug_from_url("https://landcarbonlab.org/insights/sample-post/")
        == "sample-post"
    )


def test_parse_meta_extracts_open_graph_fields() -> None:
    html = """\
    <html><head>
    <meta property="og:title" content="Sample Title" />
    <meta name="description" content="Sample abstract" />
    <meta property="og:image" content="https://example.org/image.png" />
    <meta property="og:image:alt" content="Image alt" />
    <meta property="article:published_time" content="2026-06-01T00:00:00Z" />
    </head><body></body></html>
    """
    assert store._parse_meta(html) == {
        "title": "Sample Title",
        "abstract": "Sample abstract",
        "image": "https://example.org/image.png",
        "image_alt": "Image alt",
        "lastmod": "2026-06-01T00:00:00Z",
    }
