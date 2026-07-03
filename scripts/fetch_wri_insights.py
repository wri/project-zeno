#!/usr/bin/env python3
"""Fetch WRI Insights articles from the sitemap into data/insights/wri/."""

from __future__ import annotations

import argparse

from src.agent.tools.wri_insights_store import sync_articles


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch WRI Insights blog posts into data/insights/wri/"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of articles to fetch (newest first)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch articles even if lastmod unchanged",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay between requests in seconds",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel fetch workers",
    )
    args = parser.parse_args()

    stats = sync_articles(
        limit=args.limit,
        force=args.force,
        delay_s=args.delay,
        workers=args.workers,
    )
    print(stats)


if __name__ == "__main__":
    main()
