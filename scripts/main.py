"""Fetch the latest episodes of each configured show, summarize the new full
episodes, and write them to docs/episodes.json for the static site to render.

Run:  ANTHROPIC_API_KEY=... python scripts/main.py
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import pathlib

import feedparser

from feeds import FEEDS
from summarize import summarize
from transcripts import get_transcript

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "docs" / "episodes.json"
STATE_FILE = ROOT / "docs" / "state.json"

# How many not-yet-seen *full episodes* to summarize per show per run. Bounds
# cost and keeps a first run from summarizing an entire back catalog at once.
MAX_NEW_PER_FEED = int(os.environ.get("MAX_NEW_PER_FEED", "3"))

# The show feeds interleave full episodes with short promo clips. Full episodes
# run tens of thousands of characters; clips are a couple thousand. Anything
# shorter than this is treated as a clip and skipped.
MIN_FULL_EPISODE_CHARS = int(os.environ.get("MIN_FULL_EPISODE_CHARS", "10000"))


def load_episodes() -> list[dict]:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save_episodes(episodes: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(episodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_processed() -> set[str]:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")).get("processed", []))
    return set()


def save_processed(processed: set[str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"processed": sorted(processed)}, indent=2) + "\n", encoding="utf-8"
    )


def _published_iso(entry) -> str | None:
    """feedparser gives a UTC struct_time; turn it into an ISO string that sorts
    correctly lexicographically."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(parsed), tz=dt.timezone.utc).isoformat()


def main() -> None:
    episodes = load_episodes()
    # `processed` = every video we've decided about: summarized OR skipped as a
    # clip. Videos whose transcript simply wasn't available are NOT in here, so
    # they get retried on the next run.
    processed = load_processed() | {e["id"] for e in episodes}
    new_total = 0

    for feed in FEEDS:
        parsed = feedparser.parse(feed["youtube_rss"])
        if parsed.bozo and not parsed.entries:
            print(f"[{feed['name']}] could not read feed: {parsed.get('bozo_exception')}")
            continue

        added = 0
        for entry in parsed.entries:
            if added >= MAX_NEW_PER_FEED:
                break

            video_id = entry.get("yt_videoid") or entry.get("id")
            if not video_id or video_id in processed:
                continue

            title = entry.get("title", "Untitled")
            print(f"[{feed['name']}] new: {title} ({video_id})")

            transcript = get_transcript(entry, feed)
            if not transcript:
                print("  no transcript available yet — will retry next run")
                continue  # not marked processed -> retried later

            if len(transcript) < MIN_FULL_EPISODE_CHARS:
                print(f"  looks like a clip ({len(transcript):,} chars) — skipping")
                processed.add(video_id)  # a clip stays a clip; don't reprocess
                continue

            try:
                summary = summarize(feed["name"], title, transcript)
            except Exception as exc:  # noqa: BLE001 - never let one episode kill the run
                print(f"  summarize failed: {exc}")
                continue  # not marked processed -> retried later

            thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            media = entry.get("media_thumbnail")
            if media:
                thumbnail = media[0].get("url", thumbnail)

            episodes.append(
                {
                    "id": video_id,
                    "show": feed["name"],
                    "slug": feed["slug"],
                    "title": title,
                    "url": entry.get("link"),
                    "published": _published_iso(entry),
                    "thumbnail": thumbnail,
                    "summary": summary.model_dump(),
                    "added_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            )
            processed.add(video_id)
            added += 1
            new_total += 1
            print("  summarized ✓")

    episodes.sort(key=lambda e: e.get("published") or e.get("added_at") or "", reverse=True)
    save_episodes(episodes)
    save_processed(processed)
    print(f"Done. {new_total} new episode(s) added. {len(episodes)} total.")


if __name__ == "__main__":
    main()
