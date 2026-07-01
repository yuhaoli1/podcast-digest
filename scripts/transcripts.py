"""Get an episode's transcript text, trying each show's configured sources in order.

Sources:
  - lex_site : scrape lexfridman.com/<slug>-transcript (has speaker labels)
  - youtube  : YouTube auto-captions (blocked from datacenter IPs)
  - whisper  : download the episode MP3 and transcribe with faster-whisper
               (works from any IP; no speaker labels)

Returns plain text, or None if no source produced usable text, in which case the
caller skips the episode and retries on the next run.
"""

from __future__ import annotations

import os
import re
import tempfile

import requests
from bs4 import BeautifulSoup

_UA = {"User-Agent": "Mozilla/5.0 (compatible; podcast-digest/1.0)"}
_LEX_URL_RE = re.compile(r"https?://lexfridman\.com/[a-z0-9-]+-transcript", re.IGNORECASE)
_MIN_CHARS = 500  # shorter than this isn't a real transcript


def get_transcript(entry, feed) -> str | None:
    for source in feed.get("transcript_sources", ["youtube"]):
        try:
            if source == "youtube":
                text = _from_youtube(entry.get("yt_videoid") or entry.get("id"))
            elif source == "lex_site":
                text = _from_lex_site(entry)
            elif source == "whisper":
                text = _from_whisper(entry)
            else:
                print(f"  unknown transcript source: {source}")
                text = None
        except Exception as exc:  # noqa: BLE001 - try the next source, never crash the run
            print(f"  [{source}] {type(exc).__name__}: {exc}")
            text = None

        if text and len(text) >= _MIN_CHARS:
            print(f"  transcript via {source} ({len(text):,} chars)")
            return text
    return None


# --- YouTube captions ---------------------------------------------------------

def _build_yt_api():
    from youtube_transcript_api import YouTubeTranscriptApi

    ws_user = os.environ.get("WEBSHARE_PROXY_USERNAME")
    ws_pass = os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if ws_user and ws_pass:
        from youtube_transcript_api.proxies import WebshareProxyConfig

        return YouTubeTranscriptApi(
            proxy_config=WebshareProxyConfig(proxy_username=ws_user, proxy_password=ws_pass)
        )

    http_proxy = os.environ.get("YT_PROXY_HTTP")
    https_proxy = os.environ.get("YT_PROXY_HTTPS")
    if http_proxy or https_proxy:
        from youtube_transcript_api.proxies import GenericProxyConfig

        return YouTubeTranscriptApi(
            proxy_config=GenericProxyConfig(http_url=http_proxy, https_url=https_proxy)
        )

    return YouTubeTranscriptApi()


def _from_youtube(video_id: str | None) -> str | None:
    if not video_id:
        return None
    api = _build_yt_api()
    try:
        fetched = api.fetch(video_id, languages=["en", "en-US", "en-GB"])
    except Exception:
        # No English track — take whatever transcript is available.
        transcript = next(iter(api.list(video_id)))
        fetched = transcript.fetch()
    return " ".join(snippet.text for snippet in fetched).strip()


# --- Lex Fridman official transcript page -------------------------------------

def _from_lex_site(entry) -> str | None:
    url = _find_lex_transcript_url(entry)
    if not url:
        return None
    resp = requests.get(url, headers=_UA, timeout=30)
    if resp.status_code != 200:  # 404 = not published yet; retry next run
        return None
    return _parse_lex_html(resp.text)


def _find_lex_transcript_url(entry) -> str | None:
    parts: list[str] = []
    for key in ("summary", "media_description", "title"):
        value = entry.get(key)
        if isinstance(value, str):
            parts.append(value)
    for content in entry.get("content", []) or []:
        parts.append(content.get("value", ""))
    match = _LEX_URL_RE.search(" ".join(parts))
    return match.group(0) if match else None


def _parse_lex_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    segments = soup.select(".ts-segment")
    if segments:
        lines = []
        for seg in segments:
            name = seg.select_one(".ts-name")
            text = seg.select_one(".ts-text")
            speaker = name.get_text(strip=True) if name else ""
            spoken = (text or seg).get_text(" ", strip=True)
            lines.append(f"{speaker}: {spoken}" if speaker else spoken)
        joined = "\n".join(lines).strip()
        if len(joined) >= _MIN_CHARS:
            return joined

    for selector in ("article", ".entry-content", "main", "#content"):
        node = soup.select_one(selector)
        if not node:
            continue
        for junk in node.select("script, style, nav, header, footer"):
            junk.decompose()
        text = node.get_text("\n", strip=True)
        if len(text) >= _MIN_CHARS:
            return text
    return None


# --- Whisper transcription of the episode audio -------------------------------

_whisper_models: dict = {}


def _from_whisper(entry) -> str | None:
    audio_url = _enclosure_url(entry)
    if not audio_url:
        print("  no audio enclosure in feed entry")
        return None

    path = _download_audio(audio_url)
    try:
        return _transcribe(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _enclosure_url(entry) -> str | None:
    for enc in entry.get("enclosures", []) or []:
        if str(enc.get("type", "")).startswith("audio"):
            return enc.get("href") or enc.get("url")
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("audio"):
            return link.get("href")
    return None


def _download_audio(url: str) -> str:
    cap_bytes = int(os.environ.get("MAX_AUDIO_MB", "500")) * 1024 * 1024
    resp = requests.get(url, headers=_UA, stream=True, timeout=120, allow_redirects=True)
    resp.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=".mp3")
    total = 0
    with os.fdopen(fd, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if not chunk:
                continue
            f.write(chunk)
            total += len(chunk)
            if total > cap_bytes:  # guard against absurdly large files
                print(f"  audio exceeded {cap_bytes // (1024*1024)}MB cap — truncating")
                break
    print(f"  downloaded audio ({total // (1024*1024)}MB)")
    return path


def _get_whisper_model(model_name: str):
    if model_name not in _whisper_models:
        from faster_whisper import WhisperModel

        # int8 on CPU is the fastest usable setting on a GitHub runner.
        _whisper_models[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _whisper_models[model_name]


def _transcribe(path: str) -> str:
    model_name = os.environ.get("WHISPER_MODEL", "base.en")
    model = _get_whisper_model(model_name)
    segments, _info = model.transcribe(path, language="en", vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()
