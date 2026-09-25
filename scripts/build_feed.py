#!/usr/bin/env python3
"""
FFIP LinkedIn rotation feed.

Each run adds ONE item to docs/linkedin.xml:
  1. the newest unposted article from the live blog feed, if any, otherwise
  2. the next article from the shuffled back-catalog queue.

Make.com's "Watch RSS feed items" reads the feed 3x/day and posts
each new item to the FFIP LinkedIn Page. Stdlib only, no secrets.
"""
import datetime as dt
import html
import json
import random
import re
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

SITE = "https://ffipodcast.com"
BLOG = "fly-fishing-insider-podcast-blog"
SITEMAP = f"{SITE}/sitemap_blogs_1.xml"
ATOM = f"{SITE}/blogs/{BLOG}.atom"
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state.json"
FEED = ROOT / "docs" / "linkedin.xml"
KEEP_ITEMS = 30          # ~10 days of history in the feed
UA = {"User-Agent": "FFIP-feed-bot/1.0 (+https://ffipodcast.com)"}


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def article_urls() -> list[str]:
    xml = get(SITEMAP)
    urls = re.findall(r"<loc>([^<]+)</loc>", xml)
    prefix = f"{SITE}/blogs/{BLOG}/"
    return sorted({u.strip() for u in urls if u.startswith(prefix)})


def newest_urls() -> list[str]:
    """Article links from the live Atom feed, newest first."""
    xml = get(ATOM)
    links = re.findall(r'<link[^>]+rel="alternate"[^>]+href="([^"]+)"', xml)
    prefix = f"{SITE}/blogs/{BLOG}/"
    return [u for u in links if u.startswith(prefix)]


def meta(page: str, prop: str) -> str:
    m = re.search(
        rf'<meta[^>]+(?:property|name)="{prop}"[^>]+content="([^"]*)"', page
    ) or re.search(
        rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{prop}"', page
    )
    return html.unescape(m.group(1)).strip() if m else ""


def article_details(url: str) -> dict:
    page = get(url)
    title = meta(page, "og:title") or url.rsplit("/", 1)[-1].replace("-", " ").title()
    desc = meta(page, "og:description") or meta(page, "description")
    image = meta(page, "og:image")
    if image.startswith("//"):
        image = "https:" + image
    return {"url": url, "title": title, "summary": desc, "image": image}


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"posted": [], "queue": [], "items": []}


def refill_queue(state: dict, all_urls: list[str]) -> None:
    """Shuffle every article not yet posted this cycle; start a new cycle when empty."""
    posted = set(state["posted"])
    remaining = [u for u in all_urls if u not in posted]
    if not remaining:                      # whole catalog done: start cycle 2
        state["posted"] = []
        remaining = list(all_urls)
    rng = random.Random(len(state["posted"]) + len(all_urls))
    rng.shuffle(remaining)                 # mixes topics day to day
    state["queue"] = remaining


def pick_next(state: dict) -> str | None:
    all_urls = article_urls()
    posted = set(state["posted"])
    # 1) any brand-new article not yet posted
    latest = newest_urls()
    if "seen_new" not in state:            # first run: current feed is the baseline
        state["seen_new"] = latest
    for u in latest:
        if u not in posted and u not in state.get("seen_new", []):
            state.setdefault("seen_new", []).append(u)
            return u
    # 2) back catalog
    state["queue"] = [u for u in state["queue"] if u in all_urls and u not in posted]
    if not state["queue"]:
        refill_queue(state, all_urls)
    return state["queue"].pop(0) if state["queue"] else None


def write_feed(items: list[dict]) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        "<title>FFIP LinkedIn rotation</title>",
        f"<link>{SITE}/blogs/{BLOG}</link>",
        "<description>Fly Fishing Insider Podcast articles queued for LinkedIn</description>",
        f"<lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>",
    ]
    for it in reversed(items):            # newest first, standard RSS order
        parts += [
            "<item>",
            f"<title>{escape(it['title'])}</title>",
            f"<link>{escape(it['url'])}</link>",
            f"<guid isPermaLink=\"false\">{escape(it['guid'])}</guid>",
            f"<pubDate>{it['pubDate']}</pubDate>",
            f"<description>{escape(it['summary'])}</description>",
        ]
        if it.get("image"):
            parts.append(f'<enclosure url="{escape(it["image"])}" type="image/jpeg" length="0"/>')
        parts.append("</item>")
    parts.append("</channel></rss>")
    FEED.parent.mkdir(parents=True, exist_ok=True)
    FEED.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    state = load_state()
    url = pick_next(state)
    if url:
        d = article_details(url)
        now = dt.datetime.now(dt.timezone.utc)
        d["pubDate"] = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
        d["guid"] = f"{url}#{now.strftime('%Y%m%d%H%M')}"
        state["posted"].append(url)
        state["items"] = (state["items"] + [d])[-KEEP_ITEMS:]
        print(f"Queued: {d['title']} -> {url}")
    else:
        print("Nothing to queue.")
    write_feed(state["items"])
    STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
