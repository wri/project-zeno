"""Tests for the blog card metadata endpoint."""

from unittest.mock import patch

import pytest

FAKE_INDEX = {
    "my-article": {
        "slug": "my-article",
        "title": "My Article",
        "abstract": "An abstract.",
        "url": "https://www.wri.org/insights/my-article",
        "lastmod": "2026-01-01T00:00Z",
        "image": "https://files.wri.org/hero.jpg",
        "image_alt": "A hero image",
    },
    "pre-image-article": {
        "slug": "pre-image-article",
        "title": "Older Article",
        "abstract": "Indexed before og:image capture.",
        "url": "https://www.wri.org/insights/pre-image-article",
        "lastmod": "2025-01-01T00:00Z",
    },
}


@pytest.mark.asyncio
async def test_blog_metadata_resolves_urls(client):
    """Known URLs resolve to cards keyed by the requested URL string."""
    with patch(
        "src.api.routers.blogs._articles_by_slug", return_value=FAKE_INDEX
    ):
        response = await client.get(
            "/api/blogs/metadata",
            params=[
                ("url", "https://www.wri.org/insights/my-article"),
                ("url", "https://www.wri.org/insights/my-article#p3"),
                ("url", "https://www.wri.org/insights/my-article?utm=x"),
                ("url", "https://www.wri.org/insights/unknown-article"),
            ],
        )

    assert response.status_code == 200
    articles = response.json()["articles"]
    assert set(articles) == {
        "https://www.wri.org/insights/my-article",
        "https://www.wri.org/insights/my-article#p3",
        "https://www.wri.org/insights/my-article?utm=x",
    }
    card = articles["https://www.wri.org/insights/my-article#p3"]
    assert card["title"] == "My Article"
    assert card["abstract"] == "An abstract."
    assert card["image"] == "https://files.wri.org/hero.jpg"
    assert card["image_alt"] == "A hero image"
    assert card["url"] == "https://www.wri.org/insights/my-article"


@pytest.mark.asyncio
async def test_blog_metadata_defaults_missing_image_fields(client):
    """Entries from before og:image capture return empty image fields."""
    with patch(
        "src.api.routers.blogs._articles_by_slug", return_value=FAKE_INDEX
    ):
        response = await client.get(
            "/api/blogs/metadata",
            params=[("url", "https://www.wri.org/insights/pre-image-article")],
        )

    card = response.json()["articles"][
        "https://www.wri.org/insights/pre-image-article"
    ]
    assert card["title"] == "Older Article"
    assert card["image"] == ""
    assert card["image_alt"] == ""


@pytest.mark.asyncio
async def test_blog_metadata_requires_url_param(client):
    response = await client.get("/api/blogs/metadata")
    assert response.status_code == 422
