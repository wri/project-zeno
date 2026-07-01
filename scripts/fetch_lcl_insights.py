#!/usr/bin/env python3
"""Fetch LCL Insights articles into data/insights/lcl/."""

from __future__ import annotations

import argparse

from src.agent.tools.lcl_insights_store import sync_articles


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch LCL Insights blog posts into data/insights/lcl/"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of articles to fetch",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch articles even if they already exist",
    )
    args = parser.parse_args()
    print(sync_articles(limit=args.limit, force=args.force))


if __name__ == "__main__":
    main()
