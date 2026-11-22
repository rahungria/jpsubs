# Accuracy notes

What has been measured about the Whisper path, what changed as a result, and what was tried and
shelved. Written in November 2026. Results for language models are specific to the versions named.

## How accuracy is measured

- **Text and kanji match.** An episode that carries a human-made Japanese subtitle track is
  transcribed with `--whisper-only` and compared with that track, ignoring punctuation, spaces and
  speaker labels. "Kanji match" is the share of kanji in the human track that Whisper wrote in the
  same place. The human track is not a perfect reference: it sometimes writes a word in kanji where
  kana is equally correct, so the scores understate accuracy a little.
- **Dialogue coverage.** Another subtitle track in the file shows when dialogue happens. A dialogue
  line counts as "without a Japanese line" when no generated line lies within 0.6 s of it.

Two episodes were used: **A** has a human-made Japanese track (976 kanji, 365 dialogue lines), **B**
does not (327 dialogue lines). One point of kanji match on episode A is about 10 kanji, so small
differences below are within noise.

## Missed lines (fixed by the second look)

About 5% of dialogue lines got no Japanese line, mostly short one-liners. Nearly all of them sat in
audio that the voice filter in front of Whisper discarded. Changing the filter's sensitivity moves
the misses around instead of removing them (episode B):

| Voice filter threshold | Dialogue lines without a Japanese line |
|---|---|
| 0.5 (default) | 18 |
| 0.3 | 23 |
| 0.15 | 13 |
| 0.05 | 10 |
| filter off | 10, and lines outside dialogue rose from 3 to 12 |

What shipped: after the first pass, stretches that have dialogue but no Japanese line are transcribed
again on their own without the filter (`gapfill.py`).

| Episode | Without a Japanese line, before | After |
|---|---|---|
| A | 16 of 365 | 3 |
| B | 18 of 327 | 1 |

Recovered lines are short and quiet and less reliable than the rest: of 14 compared with the human
track, 6 were right, 4 partly right and 4 wrong. Whisper's confidence does not separate the wrong
ones (wrong lines scored as high as -0.25, right ones as low as -0.98), so the cutoff of -1.0 only
removes the clearest guesses.

## Wrong kanji for words that sound alike (not fixed)

Whisper hears the sounds but sometimes writes a different word with the same pronunciation, for
example 各人物 where 書く人物 was said. On episode A:

| Kanji in the human track | Count | Share |
|---|---|---|
| Written the same by Whisper | 922 | 94.5% |
| Same sound, different kanji | 23 | 2.4% |
| Same sound, written in kana | 8 | 0.8% |
| Different sound (misheard or reworded) | 17 | 1.7% |
| Not transcribed | 6 | 0.6% |

About 12 of the 31 same-sound differences are spelling choices (すべて for 全て), not mistakes, so
the real room for improvement is close to 2 points.

### Whisper settings: no effect

Kanji match on episode A, measured before the second look existed:

| Setting | Kanji match |
|---|---|
| `large-v3-turbo` (default) | 94.3% |
| `large-v3-turbo`, previous lines as context | 94.3% |
| `large-v3` | 93.6% |
| `large-v3`, previous lines as context | 92.8% |
| Majority of 5 passes with different voice-filter settings | 94.4% |

- A glossary of show terms as prompt or hotwords, and a wider beam, did not fix the example line.
- The example line comes out right or wrong depending on where the 30-second windows fall, and was
  wrong in every full-episode variant.
- Confidence is no guide: the wrong word in the example was written at 0.89. Treating words under
  0.85 as doubtful catches 24 of 67 wrong kanji words and flags 52 of 899 correct ones.

### Correction with a local language model: shelved

Design that was tested: send lines in batches, each with the translated subtitle for the same moment
as a hint, and ask a language model for corrected lines. A proposal is accepted only if it is
pronounced exactly like the original (readings from `fugashi` with `unidic-lite`) and changes
nothing but kanji, so the model can change how a word is written but not what was said. It talks to
any server with an OpenAI-style chat API; the tests used Ollama on a 12 GB GPU with reasoning off.

Episode A, starting from 94.5%:

| Model | Kanji match after | Lines fixed / made worse | Time per episode |
|---|---|---|---|
| `gemma4:12b` | 95.4% | 8 / 0 | 12 to 20 s |
| `qwen3.5:9b` | 94.8% | 4 / 0 | about 30 s |
| `llm-jp-4.1` 8B (q6_k) | 94.5% | 0 / 0, proposed nothing | about 5 s |
| `nemotron-nano-9b-v2-japanese` | 94.5% | 0 / 0, every proposal refused | about 45 s |

- The translated hints matter: without them Gemma's gain drops from 0.9 to 0.4 points.
- Batch size (10, 20 or 40 lines) and asking for every line back instead of changed lines only made
  no real difference (0.7 to 1.0 points).
- A second pass that was told what the first pass had fixed added nothing and made one line worse.
- The acceptance checks earned their place: of the Gemma proposals the sound check refused, 6 would
  have made the line worse and 3 better.
- Reasoning mode never produced an answer. Gemma and Qwen both used their whole token budget, at 1
  to 40 lines per request, with and without forced JSON output.
- A reply-length cap is needed: one request to a model that started repeating itself ran for eight
  minutes.
- No model changed the example line (各人物), even when it was sent alone with its hint.

Why it was shelved: the best result is about one point out of a possible two, it needs a model
server and an 8 GB download, and it does not fix the mistake that prompted the work. The correction
code and its scoring script are not in the main branch.

### Fetching human-made subtitles: not built

A human-made subtitle file avoids both problems, and `--subs` already takes one and retimes it.
Downloading them automatically from Jimaku looks feasible: its API searches by title or AniList ID
and lists a show's files with a best-effort episode filter. It needs each user's own API key (free
account) and sends the show title to Jimaku. The open work is deriving show and episode from file
names and choosing among several files for one episode.

## If this is picked up again

- Measure on several episodes. One episode cannot distinguish a one-point gain from noise.
- Models too large for a 12 GB GPU were not tested.
- The second look's recovered lines are the least reliable output and have no check of their own.
