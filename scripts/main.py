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

# Default cap on not-yet-seen episodes *worked on* per show per run (a feed can
# override with "max_per_run"). For audio feeds, each expensive transcription
# attempt counts against this whether or not it succeeds, so it bounds runtime.
MAX_NEW_PER_FEED = int(os.environ.get("MAX_NEW_PER_FEED", "3"))

# YouTube feeds interleave full episodes with short promo clips. On those feeds,
# a transcript shorter than this is treated as a clip and skipped. (Audio feeds
# have no clips, so a short transcript there is a failed transcription instead.)
MIN_FULL_EPISODE_CHARS = int(os.environ.get("MIN_FULL_EPISODE_CHARS", "10000"))

# For audio feeds, how many runs to keep retrying a failing transcription before
# giving up, so we don't re-download + re-transcribe a bad episode forever.
MAX_TRANSCRIBE_ATTEMPTS = int(os.environ.get("MAX_TRANSCRIBE_ATTEMPTS", "3"))


def load_episodes() -> list[dict]:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save_episodes(episodes: list[dict]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(episodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_state() -> tuple[set[str], dict[str, int]]:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(state.get("processed", [])), dict(state.get("attempts", {}))
    return set(), {}


def save_state(processed: set[str], attempts: dict[str, int]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"processed": sorted(processed), "attempts": attempts}, indent=2) + "\n",
        encoding="utf-8",
    )


def _note_failure(attempts: dict[str, int], processed: set[str], ep_id: str) -> int:
    """Record a failed attempt for an audio episode; give up (mark processed)
    once it's failed MAX_TRANSCRIBE_ATTEMPTS times. Returns the attempt count."""
    n = attempts.get(ep_id, 0) + 1
    if n >= MAX_TRANSCRIBE_ATTEMPTS:
        processed.add(ep_id)
        attempts.pop(ep_id, None)
    else:
        attempts[ep_id] = n
    return n


def _published_iso(entry) -> str | None:
    """feedparser gives a UTC struct_time; turn it into an ISO string that sorts
    correctly lexicographically."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return dt.datetime.fromtimestamp(calendar.timegm(parsed), tz=dt.timezone.utc).isoformat()


def _feed_image(parsed) -> str | None:
    image = parsed.feed.get("image")
    if isinstance(image, dict):
        return image.get("href") or image.get("url")
    return None


def episode_meta(entry, feed, feed_image) -> dict | None:
    """Extract id/title/url/published/thumbnail for one entry, depending on
    whether it came from a YouTube feed or a podcast audio feed. Returns None if
    the entry has no usable id."""
    published = _published_iso(entry)
    title = entry.get("title", "Untitled")

    if feed["kind"] == "youtube":
        video_id = entry.get("yt_videoid") or entry.get("id")
        if not video_id:
            return None
        thumbnail = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
        media = entry.get("media_thumbnail")
        if media:
            thumbnail = media[0].get("url", thumbnail)
        return {"id": video_id, "title": title, "url": entry.get("link"),
                "published": published, "thumbnail": thumbnail}

    # audio podcast feed
    ep_id = entry.get("id") or entry.get("guid")
    if not ep_id:
        return None
    image = entry.get("image")
    thumbnail = (image.get("href") if isinstance(image, dict) else None) or feed_image
    return {"id": ep_id, "title": title, "url": entry.get("link"),
            "published": published, "thumbnail": thumbnail}


def main() -> None:
    episodes = load_episodes()
    processed, attempts = load_state()
    processed |= {e["id"] for e in episodes}
    new_total = 0

    for feed in FEEDS:
        parsed = feedparser.parse(feed["feed_url"])
        if parsed.bozo and not parsed.entries:
            print(f"[{feed['name']}] could not read feed: {parsed.get('bozo_exception')}")
            continue

        feed_image = _feed_image(parsed)
        max_new = feed.get("max_per_run", MAX_NEW_PER_FEED)
        is_audio = feed["kind"] == "audio"
        added = 0

        for entry in parsed.entries:
            if added >= max_new:
                break

            meta = episode_meta(entry, feed, feed_image)
            if not meta or meta["id"] in processed:
                continue
            ep_id = meta["id"]
            print(f"[{feed['name']}] new: {meta['title']} ({ep_id})")

            transcript = get_transcript(entry, feed)
            good = bool(transcript) and len(transcript) >= MIN_FULL_EPISODE_CHARS

            if good:
                try:
                    summary = summarize(feed["name"], meta["title"], transcript)
                except Exception as exc:  # noqa: BLE001 - never let one episode kill the run
                    print(f"  summarize failed: {exc}")
                    if is_audio:
                        # The transcription already ran; count it against the cap
                        # and toward giving up so we don't re-transcribe forever.
                        added += 1
                        n = _note_failure(attempts, processed, ep_id)
                        if ep_id in processed:
                            print(f"  giving up after {n} attempts")
                    continue

                episodes.append(
                    {
                        "id": ep_id,
                        "show": feed["name"],
                        "slug": feed["slug"],
                        "title": meta["title"],
                        "url": meta["url"],
                        "published": meta["published"],
                        "thumbnail": meta["thumbnail"],
                        "summary": summary.model_dump(),
                        "added_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }
                )
                processed.add(ep_id)
                attempts.pop(ep_id, None)
                added += 1
                new_total += 1
                print("  summarized ✓")
                continue

            # transcript missing or too short
            if not is_audio:
                if transcript is None:
                    print("  no transcript available yet — will retry next run")
                else:
                    print(f"  looks like a clip ({len(transcript):,} chars) — skipping")
                    processed.add(ep_id)  # a clip stays a clip
                continue

            # audio feed: an expensive download+transcribe already ran but the
            # result was missing or too short (partial/garbled). Bound runtime by
            # counting it against the cap, and retry with a give-up limit.
            added += 1
            n = _note_failure(attempts, processed, ep_id)
            if ep_id in processed:
                print(f"  transcription failed/incomplete — giving up after {n} attempts")
            else:
                print(f"  transcription failed/incomplete (attempt {n}/{MAX_TRANSCRIBE_ATTEMPTS}) — retry next run")

    episodes.sort(key=lambda e: e.get("published") or e.get("added_at") or "", reverse=True)
    save_episodes(episodes)
    save_state(processed, attempts)
    print(f"Done. {new_total} new episode(s) added. {len(episodes)} total.")


if __name__ == "__main__":
    main()
