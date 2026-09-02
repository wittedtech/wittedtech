#!/usr/bin/env python3
"""Rebuild the Dev.to section of README.md, ranked by engagement.

The RSS-based blog-post-workflow action can only order posts chronologically.
Dev.to's public API exposes reaction and comment counts, so we sort on those
instead and bucket the result into three tiers.

Everything between BLOG-POST-LIST:START and BLOG-POST-LIST:END is replaced.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

USERNAME = "wittedtech-by-harshit"
API = f"https://dev.to/api/articles?username={USERNAME}&per_page=100"
README = Path(__file__).resolve().parents[2] / "README.md"

START = "<!-- BLOG-POST-LIST:START -->"
END = "<!-- BLOG-POST-LIST:END -->"

# (heading, how many posts, blurb)
TIERS = [
    ("🔥 **Top Read** — the ones that actually took off", 3,
     "What the internet decided it liked."),
    ("📈 **Medium Read** — steady performers", 3,
     "Respectable numbers, no complaints."),
    ("💎 **Least Read** — criminally underrated", 3,
     "I stand by every one of these. The algorithm disagreed."),
]


def score(article: dict) -> tuple[int, int]:
    """Comments are harder to earn than reactions, so they break ties upward."""
    return (
        article.get("public_reactions_count", 0),
        article.get("comments_count", 0),
    )


def fetch() -> list[dict]:
    req = urllib.request.Request(API, headers={"User-Agent": "wittedtech-readme-bot"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def line(a: dict) -> str:
    reactions = a.get("public_reactions_count", 0)
    comments = a.get("comments_count", 0)
    mins = a.get("reading_time_minutes")
    bits = [f"{reactions} 💜"]
    if comments:
        bits.append(f"{comments} 💬")
    if mins:
        bits.append(f"{mins} min")
    return f"- [{a['title']}]({a['url']}) · <sub>{' · '.join(bits)}</sub>"


def build(articles: list[dict]) -> str:
    ranked = sorted(articles, key=score, reverse=True)
    if not ranked:
        return "_No posts found — the Dev.to API returned nothing._"

    out: list[str] = []
    top_n, mid_n, low_n = (t[1] for t in TIERS)

    buckets = [
        ranked[:top_n],
        ranked[top_n:top_n + mid_n],
        # bottom tier, least-engaged first so the very quietest leads
        list(reversed(ranked[-low_n:])) if len(ranked) > top_n + mid_n else [],
    ]

    for (heading, _, blurb), posts in zip(TIERS, buckets):
        if not posts:
            continue
        out.append(f"#### {heading}")
        out.append(f"<sub><i>{blurb}</i></sub>")
        out.append("")
        out.extend(line(a) for a in posts)
        out.append("")

    out.append(f"<sub>Ranked by reactions and comments across {len(ranked)} posts · "
               f"refreshed daily by GitHub Actions</sub>")
    return "\n".join(out).rstrip()


def main() -> int:
    try:
        articles = fetch()
    except Exception as exc:  # noqa: BLE001 - never fail the workflow over a flaky API
        print(f"::warning::Dev.to fetch failed ({exc}); leaving README untouched")
        return 0

    text = README.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print(f"::error::Markers {START} / {END} not found in README.md")
        return 1

    section = f"{START}\n{build(articles)}\n{END}"
    updated = re.sub(
        re.escape(START) + r".*?" + re.escape(END),
        lambda _: section,
        text,
        flags=re.S,
    )

    if updated == text:
        print("No change.")
        return 0

    README.write_text(updated, encoding="utf-8")
    print(f"Updated blog section from {len(articles)} posts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
