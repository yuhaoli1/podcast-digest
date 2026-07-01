"""Turn a podcast transcript into a structured, scan-friendly summary via Claude."""

from __future__ import annotations

from typing import Literal

import anthropic
from pydantic import BaseModel

# Opus 4.8 is the default. It's plenty capable for this and cheap at the volume
# a personal digest runs (a few episodes/day). To cut cost ~5x with a small
# quality trade-off, change this to "claude-sonnet-5".
MODEL = "claude-opus-4-8"


class Topic(BaseModel):
    title: str
    detail: str


class EpisodeSummary(BaseModel):
    tldr: str
    topics: list[Topic]
    quotes: list[str]
    verdict: Literal["Must-listen", "Worth listening", "Skim-worthy", "Skip"]
    verdict_reason: str


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        # Reads ANTHROPIC_API_KEY from the environment.
        _client = anthropic.Anthropic()
    return _client


SYSTEM = (
    "You are a sharp editorial assistant who helps a busy tech, startup, and VC "
    "reader decide whether an episode is worth their time. You write in crisp, "
    "concrete language with no hype or filler. Surface what actually matters: the "
    "arguments made, specific claims, numbers, predictions, disagreements between "
    "the hosts or guests, and any genuinely memorable lines."
)

PROMPT_TEMPLATE = """Summarize this podcast episode for a quick-scan reader.

Show: {show}
Episode: {title}

Guidance:
- tldr: 2-4 sentences on what the episode is actually about and its single most important takeaway.
- topics: the 3-6 main threads. Each gets a short title and 1-3 sentences of *specific* substance \
(name the claims, numbers, people, and predictions — never "they discussed X").
- quotes: 1-4 genuinely memorable or substantive lines, quoted closely from the transcript. \
Return an empty list if nothing stands out.
- verdict: judged for a reader who follows tech, startups, and markets.
- verdict_reason: one sentence justifying the verdict.

Transcript:
{transcript}"""


def summarize(show: str, title: str, transcript: str) -> EpisodeSummary:
    """Summarize one episode. Raises on API error so the caller can skip it."""
    response = _get_client().messages.parse(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": PROMPT_TEMPLATE.format(
                    show=show, title=title, transcript=transcript
                ),
            }
        ],
        output_format=EpisodeSummary,
    )
    summary = response.parsed_output
    if summary is None:  # safety refusal or schema miss
        raise RuntimeError(f"model did not return a valid summary (stop_reason={response.stop_reason})")
    return summary
