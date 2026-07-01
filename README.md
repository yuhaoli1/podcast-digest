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
scripts/transcripts.py   per-show transcript fetching (Lex site scrape + YouTube captions)
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

## The one caveat: All-In transcripts in the cloud

The two shows get their transcripts differently:

- **Lex Fridman** publishes official transcripts on his site. These are fetched
  directly and work perfectly from GitHub's servers. ✅
- **All-In** has no official transcript, so the only text source is YouTube's
  auto-captions — and **YouTube blocks datacenter IPs**, which is what GitHub
  Actions runs on. So All-In summaries won't appear from the cloud job by default.

If an episode's transcript can't be fetched, it's simply **skipped and retried on
the next run** — nothing breaks. To actually get All-In working, pick one:

**Option A — run the fetch on your Mac (free).**
Your home IP isn't blocked, so this just works. From the project folder:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/main.py
git add docs/episodes.json && git commit -m "digest" && git push
```

You can do this whenever you want to backfill; the site (on Pages) stays live
regardless. To automate it, schedule that command with `cron`/`launchd`.

**Option B — add a residential proxy (a few $/month, stays fully cloud).**
Sign up for a **Webshare "Residential"** (rotating) proxy, then add two repo
secrets: `WEBSHARE_PROXY_USERNAME` and `WEBSHARE_PROXY_PASSWORD`. The job picks
them up automatically and All-In starts working from the cloud. (A generic proxy
also works via `YT_PROXY_HTTP` / `YT_PROXY_HTTPS`.)

Lex works either way, so if you don't set this up you'll still get a working
Lex Fridman digest in the cloud from day one.

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
