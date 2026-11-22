"""Pure text/timing helpers: cue cleanup, segment splitting, SRT output."""

from __future__ import annotations

import re
from dataclasses import dataclass

SENTENCE_END = "。！？!?…"
CLAUSE_END = "、,，"
MAX_CHARS = 28
MAX_WORD_GAP = 1.5  # seconds of silence inside a segment that forces a split
MIN_PAUSE_SPLIT = 0.25  # a pause this long is an acceptable place to break a long line
MIN_DURATION = 0.7
MAX_DURATION = 10.0

# Lines Whisper invents over silence, music and credits.
HALLUCINATIONS = [
    r"ご視聴ありがとうございま(した|す)",
    r"ご清聴ありがとうございま(した|す)",
    r"チャンネル登録",
    r"高評価",
    r"字幕(視聴|作成|提供|は)",
    r"次回予告$",
    r"^最後までご視聴",
    r"提供は.*お送りしま",
    r"^おやすみなさい$",
    r"^(by|subtitles? by)\b",
    r"amara\.org",
]
_HALLUCINATION_RE = re.compile("|".join(HALLUCINATIONS), re.IGNORECASE)
_JAPANESE_RE = re.compile(r"[぀-ヿ一-鿿]")
_HAS_TEXT_RE = re.compile(r"[\w぀-ヿ一-鿿]")


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class Word:
    start: float
    end: float
    text: str


def looks_japanese(cues: list[Cue], threshold: float = 0.5) -> bool:
    """True when most cues contain kana or kanji (guards against mislabeled tracks)."""
    texts = [c.text for c in cues if c.text.strip()]
    if not texts:
        return False
    hits = sum(1 for t in texts if _JAPANESE_RE.search(t))
    return hits / len(texts) >= threshold


def is_hallucination(text: str) -> bool:
    return bool(_HALLUCINATION_RE.search(text))


def split_words(words: list[Word], max_chars: int = MAX_CHARS) -> list[Cue]:
    """Turn one Whisper segment's words into subtitle-sized cues.

    Splits at sentence punctuation and long pauses, then breaks anything still
    too long at the clause mark closest to its middle.
    """
    groups: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur and w.start - cur[-1].end > MAX_WORD_GAP:
            if _length(cur) <= 2 and not _ends_sentence(cur[-1]):
                # Whisper often pins the first syllable of a line to the end of the
                # previous speech; it belongs with the words that follow the pause.
                cur = [Word(w.start, w.start, x.text) for x in cur]
            else:
                groups.append(cur)
                cur = []
        cur.append(w)
        if _ends_sentence(w) and _length(cur) >= 4:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    out: list[Cue] = []
    for group in groups:
        for piece in _split_long(group, max_chars):
            text = "".join(w.text for w in piece).strip()
            if text:
                out.append(Cue(piece[0].start, piece[-1].end, text))
    return out


def _length(words: list[Word]) -> int:
    return len("".join(w.text for w in words).strip())


def _ends_sentence(w: Word) -> bool:
    return w.text.strip().endswith(tuple(SENTENCE_END))


def _split_long(words: list[Word], max_chars: int) -> list[list[Word]]:
    total = _length(words)
    if total <= max_chars or len(words) < 2:
        return [words]
    cut = _best_cut(words, total, max_chars)
    if cut is None:
        return [words]
    return _split_long(words[: cut + 1], max_chars) + _split_long(words[cut + 1 :], max_chars)


def _best_cut(words: list[Word], total: int, max_chars: int) -> int | None:
    """Index of the word to cut after. Prefers a clause mark or space near the middle,
    then the longest pause, and only for very long lines an arbitrary word boundary."""
    half = total / 2
    seen = 0
    clause: list[tuple[float, int]] = []
    anywhere: list[tuple[float, int]] = []
    pauses: list[tuple[float, int]] = []
    for i, w in enumerate(words[:-1]):
        seen += len(w.text)
        nxt = words[i + 1]
        dist = abs(seen - half)
        anywhere.append((dist, i))
        text = w.text.rstrip()
        if text.endswith(tuple(CLAUSE_END)) or w.text != text or nxt.text[:1].isspace():
            clause.append((dist, i))
        pauses.append((nxt.start - w.end, i))
    if clause:
        return min(clause)[1]
    gap, i = max(pauses)
    if gap >= MIN_PAUSE_SPLIT:
        return i
    if total > max_chars * 1.5:
        return min(anywhere)[1]
    return None


def clean_cues(cues: list[Cue], drop_hallucinations: bool = False) -> list[Cue]:
    """Normalise text, drop junk, remove duplicates and fix overlapping timing."""
    out: list[Cue] = []
    for c in sorted(cues, key=lambda c: (c.start, c.end)):
        text = _normalise(c.text)
        if not text or not _HAS_TEXT_RE.search(text):
            continue
        if drop_hallucinations and is_hallucination(text):
            continue
        if c.end <= c.start:
            continue
        if out and out[-1].text == text and c.start - out[-1].end < 0.05:
            # same line layered or repeated back to back: merge
            out[-1].end = max(out[-1].end, c.end)
            continue
        out.append(Cue(c.start, c.end, text))
    if drop_hallucinations:
        out = _collapse_loops(out)
    return out


def fix_timing(cues: list[Cue]) -> list[Cue]:
    """For generated cues: enforce sane durations and no overlap with the next cue."""
    for i, c in enumerate(cues):
        nxt = cues[i + 1].start if i + 1 < len(cues) else None
        c.end = min(c.end, c.start + MAX_DURATION)
        if c.end - c.start < MIN_DURATION:
            c.end = c.start + MIN_DURATION
        if nxt is not None and c.end > nxt:
            c.end = max(nxt, c.start + 0.1)
    return cues


def _collapse_loops(cues: list[Cue], limit: int = 3) -> list[Cue]:
    """Whisper sometimes repeats one line many times; keep only the first of a run."""
    result: list[Cue] = []
    i = 0
    while i < len(cues):
        j = i
        while j + 1 < len(cues) and cues[j + 1].text == cues[i].text:
            j += 1
        # runs shorter than the limit are real speech ("はい", "はい")
        result.extend(cues[i : i + 1] if j - i + 1 >= limit else cues[i : j + 1])
        i = j + 1
    return result


def _normalise(text: str) -> str:
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.replace("\r", "").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def format_timestamp(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{format_timestamp(c.start)} --> {format_timestamp(c.end)}\n{c.text}\n"
        for i, c in enumerate(cues, 1)
    ]
    return "\n".join(blocks)
