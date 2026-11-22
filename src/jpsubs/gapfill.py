"""Second look: re-transcribe stretches where dialogue is known to happen but no line was produced.

The voice filter in front of Whisper discards some short or quiet lines. A
subtitle track in any language tells us when dialogue happens, so those
stretches can be transcribed again on their own, without the filter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from jpsubs.clean import Cue, is_hallucination

SLACK = 0.6  # a cue this close to a dialogue window counts as covering it
JOIN = 1.0  # neighbouring gaps closer than this are heard together
MAX_GAP = 12.0  # longest stretch transcribed in one go
PAD = 0.5  # audio added on each side of a gap
MIN_LOGPROB = -1.0  # below this Whisper is guessing
MAX_CHARS_PER_SECOND = 12  # faster than anyone speaks; longer text is invented

_JAPANESE_RE = re.compile(r"[぀-ヿ一-鿿]")

Window = tuple[float, float]


@dataclass
class Candidate:
    """One segment Whisper returned for a gap."""

    cues: list[Cue]
    text: str
    avg_logprob: float


class WindowTranscriber(Protocol):
    def transcribe_window(self, audio, start: float, end: float) -> list[Candidate]: ...


def find_gaps(windows: list[Window], cues: list[Cue], slack: float = SLACK) -> list[Window]:
    """Dialogue windows with no cue in or near them."""
    return [
        (start, end)
        for start, end in windows
        if not any(c.start < end + slack and c.end > start - slack for c in cues)
    ]


def merge_gaps(gaps: list[Window], join: float = JOIN, max_len: float = MAX_GAP) -> list[Window]:
    merged: list[Window] = []
    for start, end in sorted(gaps):
        if merged and start - merged[-1][1] < join and end - merged[-1][0] <= max_len:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def accept(text: str, duration: float, avg_logprob: float) -> bool:
    """Whether a second-look result is believable speech rather than an invention."""
    text = text.strip()
    if not _JAPANESE_RE.search(text) or is_hallucination(text):
        return False
    if avg_logprob < MIN_LOGPROB:
        return False
    return len(text) <= MAX_CHARS_PER_SECOND * duration


def second_look(
    transcriber: WindowTranscriber, audio, windows: list[Window], cues: list[Cue], pad: float = PAD
) -> list[Cue]:
    """New cues for dialogue windows the first pass left empty. Existing cues are not touched."""
    found: list[Cue] = []
    for start, end in merge_gaps(find_gaps(windows, cues)):
        lo, hi = max(0.0, start - pad), end + pad
        for cand in transcriber.transcribe_window(audio, lo, hi):
            if not accept(cand.text, hi - lo, cand.avg_logprob):
                continue
            for cue in cand.cues:
                if not _overlaps(cue, cues) and not _overlaps(cue, found):
                    found.append(cue)
    return found


def _overlaps(cue: Cue, others: list[Cue]) -> bool:
    return any(cue.start < o.end and cue.end > o.start for o in others)
