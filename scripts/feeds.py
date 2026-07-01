"""Which shows to follow, and where their transcripts come from.

Add a show by appending a dict here. `youtube_rss` is a keyless RSS feed
(https://www.youtube.com/feeds/videos.xml?channel_id=UC...). `transcript_sources`
is tried in order until one yields text:
  - "lex_site" : scrape the official transcript page on lexfridman.com (free, cloud-safe)
  - "youtube"  : YouTube captions via youtube-transcript-api (needs a residential
                 IP or proxy — see README; blocked from datacenter IPs)
"""

FEEDS = [
    {
        "name": "All-In",
        "slug": "all-in",
        # The main "All-In Podcast" channel (not the clips channel).
        "youtube_rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCESLZhusAkFfsNsApnjF_Cg",
        "transcript_sources": ["youtube"],
    },
    {
        "name": "Lex Fridman",
        "slug": "lex-fridman",
        "youtube_rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCSHZKyawb77ixDdsGog4iWA",
        # Prefer his official transcript page; fall back to captions if it's not
        # published yet (there's a lag) or the link isn't in the feed.
        "transcript_sources": ["lex_site", "youtube"],
    },
]
