# jpsubs

Writes a Japanese subtitle file (`<video>.ja.srt`) next to each video, so mpv shows Japanese text
that mpvacious can pass to Yomitan and Anki.

For each video the first source that works is used:

1. **Embedded Japanese text track** in the file. Tracks tagged Japanese that contain no Japanese
   text are ignored, as are image-based tracks (PGS/VobSub).
2. **A subtitle file next to the video** with the same name (`Episode 01.srt`, `Episode 01.jpn.ass`),
   or one passed with `--subs`. It is retimed to the video's Japanese audio with `alass`.
3. **Whisper speech recognition** on the GPU (`large-v3-turbo` by default), followed by a
   **second look**: the filter in front of Whisper discards some short or quiet lines, so stretches
   where another subtitle track in the file shows dialogue but no Japanese line came out are
   transcribed again on their own. Only that track's timing is used, never its text.

## Usage

```sh
jpsubs "/path/to/Show"                 # every video in the folder, recursively
jpsubs episode.mkv                     # one file
jpsubs --dry-run "/path/to/Show"       # show which source each video would use
jpsubs episode.mkv --subs download.srt # use a downloaded subtitle file, retimed
jpsubs --whisper-only episode.mkv      # ignore existing subtitles
jpsubs --force episode.mkv             # redo; the old .ja.srt is kept as .ja.srt.bak
jpsubs --model large-v3 episode.mkv    # slower model, similar accuracy
jpsubs --no-second-look episode.mkv    # first Whisper pass only
```

Videos that already have a `.ja.srt` are skipped, so re-running on a folder only does new episodes.

## Watching and mining

1. Keep Anki open.
2. Open the Yomitan search page in the browser (`Alt+Insert`) and turn on its clipboard monitor.
3. Play the video in mpv. Each subtitle line appears on the Yomitan page.
4. Look up a word there and add the card. mpvacious attaches the line's audio clip and a
   screenshot to the new card within a couple of seconds.

Useful mpv keys (mpvacious): `Ctrl+t` toggle clipboard copying, `Ctrl+h` replay from the start of
the line, `Ctrl+m` attach audio and screenshot to the last card by hand, `a` open the menu.

Config lives in `~/.config/mpv/mpv.conf` and `~/.config/mpv/script-opts/subs2srs.conf`.

## What to expect from Whisper

Measured on one episode against human-made Japanese subtitles: about 91% of the subtitle text is
recovered and about 94% of kanji are the right ones, line starts are typically within 0.3 s, and an
episode takes about 20 seconds on an RTX 5070. Names, songs, overlapping speech and words that sound
alike are where it goes wrong, so treat generated lines as a listening aid. When a human-made file
exists (for example from Jimaku), `--subs` gives better text.

The second look cut dialogue left without a line from about 5% to under 1% on two test episodes.
Lines it recovers are short and quiet, and less reliable than the rest: of 14 checked against human
subtitles, 10 were right or partly right. It needs a text subtitle track in the file (any language)
to know where dialogue is; without one, only the first pass runs. Songs are not chased.

## Known limitations

- **Words that sound alike can get the wrong kanji.** About 1 kanji in 20 differs from human-made
  subtitles, and roughly half of those are a same-sounding word written differently (進学 where 神学
  was said). No Whisper setting improves this. The audio on the card is right even when the text is
  not, so check a doubtful word by ear.
- **Lines recovered by the second look are less reliable** than the rest (see above).
- **No second look without a text subtitle track** in the file.
- **Songs** are mostly left untranscribed.
- `kotoba-whisper-v2.0-faster` crashes with this setup and is not supported.

When accuracy matters for a show, a human-made subtitle file passed with `--subs` avoids all of
these. What was measured, and what was tried and shelved (model settings, correction with a local
language model, automatic download of human-made subtitles), is in
[docs/accuracy-notes.md](docs/accuracy-notes.md).

## Development

```sh
uv run pytest
uv tool install --force -e .   # reinstall the jpsubs command after dependency changes
```

Requires `ffmpeg`, an NVIDIA GPU (or `--device cpu`), and optionally `alass-cli` for retiming.
