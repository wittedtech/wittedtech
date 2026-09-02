#!/usr/bin/env python3
"""Regenerate the data-driven sections of README.md.

Two sections, each delimited by its own marker pair:

  BLOG-POST-LIST   Dev.to posts as image cards, ranked by engagement.
                   The RSS-based blog-post-workflow action can only order
                   chronologically; the Dev.to API exposes reaction and comment
                   counts, so we rank on those and bucket into three tiers.

  RECENT-REPOS     Most recently pushed non-fork repositories.
                   Deliberately NOT the Events API: that only covers ~90 days
                   and currently returns nothing but WatchEvents for this user,
                   so a "recent commits" widget would render empty. `pushed_at`
                   is always populated.

Network failures leave the README untouched rather than failing the workflow.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEVTO_USER = "wittedtech-by-harshit"
GH_USER = "wittedtech"
README = Path(__file__).resolve().parents[2] / "README.md"

DEVTO_API = f"https://dev.to/api/articles?username={DEVTO_USER}&per_page=100"
REPOS_API = f"https://api.github.com/users/{GH_USER}/repos?per_page=100&sort=pushed"

CARD_W, CARD_H = 440, 220

TIERS = [
    ("🔥 Top Read", "The ones that actually took off.", 0, 3),
    ("📈 Medium Read", "Steady performers, no complaints.", 3, 6),
    ("💎 Least Read", "I stand by every one of these. The algorithm disagreed.", -3, None),
]


def get(url: str, accept: str | None = None) -> list | dict:
    headers = {"User-Agent": "wittedtech-readme-bot"}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
        return json.load(r)


def replace(text: str, marker: str, body: str) -> str:
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    if start not in text or end not in text:
        raise KeyError(f"markers for {marker} not found")
    return re.sub(
        re.escape(start) + r".*?" + re.escape(end),
        lambda _: f"{start}\n{body}\n{end}",
        text,
        flags=re.S,
    )


# --------------------------------------------------------------------- blog

def thumb(article: dict) -> str | None:
    """Dev.to serves images through a resizing CDN; ask for a card-sized one.

    cover_image is null on ~1/3 of posts, so fall back to social_image.
    """
    url = article.get("cover_image") or article.get("social_image")
    if not url:
        return None
    return re.sub(r"width=\d+,height=\d+", f"width={CARD_W},height={CARD_H}", url)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def card(a: dict) -> str:
    title, url = esc(a["title"]), a["url"]
    stats = [f"{a.get('public_reactions_count', 0)} 💜"]
    if a.get("comments_count"):
        stats.append(f"{a['comments_count']} 💬")
    if a.get("reading_time_minutes"):
        stats.append(f"{a['reading_time_minutes']} min")
    img = thumb(a)
    art = (f'<a href="{url}"><img src="{img}" alt="{title}" width="100%" /></a><br />'
           if img else "")
    return (
        f'    <td width="33%" valign="top">\n'
        f'      {art}\n'
        f'      <b><a href="{url}">{title}</a></b><br />\n'
        f'      <sub>{" · ".join(stats)}</sub>\n'
        f'    </td>'
    )


def build_blog(articles: list[dict]) -> str:
    ranked = sorted(
        articles,
        key=lambda a: (a.get("public_reactions_count", 0), a.get("comments_count", 0)),
        reverse=True,
    )
    if not ranked:
        return "_The Dev.to API returned no posts._"

    out: list[str] = []
    for heading, blurb, lo, hi in TIERS:
        posts = ranked[lo:hi] if hi is not None else ranked[lo:]
        if lo < 0:
            posts = list(reversed(posts))  # quietest first
        posts = [p for p in posts if p]
        if not posts:
            continue
        out += [
            f"#### {heading}",
            f"<sub><i>{blurb}</i></sub>",
            "",
            "<table>",
            "  <tr>",
            *[card(p) for p in posts],
            "  </tr>",
            "</table>",
            "",
        ]

    out.append(
        f"<sub>Ranked by reactions and comments across {len(ranked)} posts · "
        f"rebuilt daily by GitHub Actions</sub>"
    )
    return "\n".join(out).rstrip()


# ------------------------------------------------------------------- repos

def ago(iso: str) -> str:
    d = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days
    if d <= 0:
        return "today"
    if d == 1:
        return "yesterday"
    if d < 30:
        return f"{d} days ago"
    if d < 365:
        return f"{d // 30} mo ago"
    y = d // 365
    return "1 year ago" if y == 1 else f"{y} years ago"


def build_repos(repos: list[dict], limit: int = 6) -> str:
    own = [r for r in repos if not r.get("fork")]
    own.sort(key=lambda r: r["pushed_at"], reverse=True)
    rows = ["| Repository | Language | What it is | Last push |", "|---|---|---|---|"]
    for r in own[:limit]:
        lang = r.get("language") or "—"
        desc = (r.get("description") or "—").strip()
        if len(desc) > 62:
            desc = desc[:59].rstrip() + "…"
        stars = f" ⭐{r['stargazers_count']}" if r["stargazers_count"] else ""
        rows.append(
            f"| **[{r['name']}]({r['html_url']})**{stars} | `{lang}` | {desc} | {ago(r['pushed_at'])} |"
        )
    return "\n".join(rows)


# -------------------------------------------------------------------- main

def main() -> int:
    text = README.read_text(encoding="utf-8")
    original = text
    changed = []

    for marker, url, accept, builder in (
        ("BLOG-POST-LIST", DEVTO_API, None, build_blog),
        ("RECENT-REPOS", REPOS_API, "application/vnd.github+json", build_repos),
    ):
        try:
            data = get(url, accept)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"::warning::{marker}: fetch failed ({exc}); section left as-is")
            continue
        try:
            text = replace(text, marker, builder(data))
        except KeyError as exc:
            print(f"::error::{exc}")
            return 1
        changed.append(marker)

    if text == original:
        print("No change.")
        return 0

    README.write_text(text, encoding="utf-8")
    print(f"Updated: {', '.join(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
