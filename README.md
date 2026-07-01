# Podcast Digest

A tiny, free, self-updating website that summarizes new episodes of the podcasts
you follow (starting with **All-In** and **Lex Fridman**) so you can skim what
was covered and decide whether it's worth a full listen.

- A scheduled job reads each show's feed, pulls the episode transcript, and has
  Claude write a structured summary (TL;DR, what it covered, notable quotes, and
  a "worth it?" verdict).
- The summaries are rendered as cards on a static web page you can open anywhere.
- It runs on **GitHub Actions** (cron) and is served by **GitHub Pages** — no
  server to run, nothing to pay for (aside from Claude API usage, ~pennies/episode).

```
scripts/main.py          orchestrates a run
scripts/feeds.py         which shows to follow
scripts/transcripts.py   per-show transcript fetching (Lex site scrape, YouTube captions, Whisper audio)
scripts/summarize.py     Claude summarization -> structured JSON
docs/index.html          the web page (static, committed once)
docs/episodes.json       the data the page renders (updated by the job)
.github/workflows/update.yml   the daily cron job
```

## Setup (about 10 minutes)

1. **Create a repo and push this folder to it.**

2. **Add your Anthropic API key** as a repo secret:
   Repo → *Settings → Secrets and variables → Actions → New repository secret*
   - Name: `ANTHROPIC_API_KEY`
   - Value: your key from https://console.anthropic.com

3. **Turn on GitHub Pages:**
   Repo → *Settings → Pages* → *Source: Deploy from a branch* →
   Branch: `main`, Folder: `/docs` → *Save*.
   Your site will be at `https://<your-username>.github.io/<repo-name>/`.

4. **Run it once** to populate the page:
   Repo → *Actions → "Update podcast digest" → Run workflow*.
   After it finishes it commits `docs/episodes.json`; refresh your Pages URL.

After that it runs itself once a day (14:00 UTC — edit the `cron` line in
`.github/workflows/update.yml` to change the time).

## How each show gets its transcript

The two shows get their text differently — both work fully in the cloud:

- **Lex Fridman** publishes official transcripts on his site. These are scraped
  directly (fast, and they include speaker labels). ✅
- **All-In** has no official transcript, so the job downloads the episode's MP3
  from its podcast feed and transcribes it with **faster-whisper** on the runner.
  This works from any IP (no proxy needed), but it's **slow** — transcribing a
  full ~2-hour episode takes roughly 30–60 minutes of runner time. So All-In is
  capped at **one episode per run** (`max_per_run` in `feeds.py`) and backfills
  over several daily runs before keeping up in real time. Whisper transcripts
  have no speaker labels, so All-In summaries won't attribute a take to a specific
  host as precisely as Lex's do.

If a transcript can't be produced (e.g. a brand-new episode), it's simply
**skipped and retried on the next run** — nothing breaks.

**Tuning transcription:**
- `WHISPER_MODEL` (default `base.en`) — set to `small.en` for better accuracy on
  names/companies at ~2× the time, or `tiny.en` for speed.
- All-In runtime is free on GitHub Actions (public repos get unlimited minutes);
  the daily job carries a 180-minute timeout.

**Faster alternative for YouTube-caption shows:** for any show configured with the
`youtube` transcript source (not All-In, which uses audio), captions are blocked
from datacenter IPs. Add a **Webshare Residential** proxy via the
`WEBSHARE_PROXY_USERNAME` / `WEBSHARE_PROXY_PASSWORD` repo secrets (or a generic
one via `YT_PROXY_HTTP` / `YT_PROXY_HTTPS`) and they'll work from the cloud too.

## Customizing

- **Add shows:** append to `FEEDS` in `scripts/feeds.py`. Find a channel's RSS at
  `https://www.youtube.com/feeds/videos.xml?channel_id=UC...`. Use
  `["youtube"]` for transcript sources (or add a site-scraper like the Lex one).
- **Change the model / cost:** `MODEL` in `scripts/summarize.py` (default
  `claude-opus-4-8`; switch to `claude-sonnet-5` for ~5x lower cost).
- **How many new episodes per run:** `MAX_NEW_PER_FEED` env var (default 3).
- **Clips vs. full episodes:** the show feeds mix short promo clips in with full
  episodes; anything under `MIN_FULL_EPISODE_CHARS` characters of transcript
  (default 10,000) is treated as a clip and skipped. Lower it if you want the
  clips summarized too.
- **Tune the summary:** edit the prompt in `scripts/summarize.py`.

## How state is tracked

`docs/episodes.json` holds the summaries the page renders. `docs/state.json`
records every video that's been handled — summarized *or* skipped as a clip — so
they aren't reprocessed. A video whose transcript wasn't available (e.g. a brand
new episode before captions/transcript exist) is left out of both and retried on
the next run.
