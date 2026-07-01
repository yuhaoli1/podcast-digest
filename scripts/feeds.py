"""Which shows to follow, where to discover episodes, and how to get transcripts.

Each feed has:
  - kind: "youtube" (a YouTube channel RSS) or "audio" (a podcast RSS with MP3s)
  - feed_url: the RSS URL
  - transcript_sources: tried in order until one yields text
      "lex_site" : scrape the official transcript page on lexfridman.com (free, cloud-safe)
      "youtube"  : YouTube captions (blocked from datacenter IPs — see README)
      "whisper"  : download the episode's MP3 and transcribe it locally with
                   faster-whisper (works from any IP, incl. GitHub Actions)
  - max_per_run: optional cap on new episodes summarized per run (defaults to
      MAX_NEW_PER_FEED). Whisper transcription is slow, so All-In is capped low
      and backfills over several daily runs.
"""

FEEDS = [
    {
        "name": "All-In",
        "slug": "all-in",
        "kind": "audio",
        # The official audio feed (Libsyn). Full episodes only — no clips — and
        # the MP3s download fine from any IP, so this works in the cloud.
        "feed_url": "https://allinchamathjason.libsyn.com/rss",
        "transcript_sources": ["whisper"],
        "max_per_run": 1,  # ~30-60 min to transcribe an episode; backfills daily
    },
    {
        "name": "Lex Fridman",
        "slug": "lex-fridman",
        "kind": "youtube",
        "feed_url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCSHZKyawb77ixDdsGog4iWA",
        # Prefer his official transcript page; fall back to captions if it's not
        # published yet (there's a lag) or the link isn't in the feed.
        "transcript_sources": ["lex_site", "youtube"],
    },
]
