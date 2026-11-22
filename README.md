# jpsubs

Writes a Japanese subtitle file (`<video>.ja.srt`) next to each video, so mpv shows Japanese text
that mpvacious can pass to Yomitan and Anki.

For each video the first source that works is used:

1. **Embedded Japanese text track** in the file. Tracks tagged Japanese that contain no Japanese
   text are ignored, as are image-based tracks (PGS/VobSub).
2. **A subtitle file next to the video** with the same name (`Episode 01.srt`, `Episode 01.jpn.ass`),
   or one passed with `--subs`. It is retimed to the video's Japanese audio with `alass`.
3. **Whisper speech recognition** on the GPU (`large-v3-turbo` by default).

## Usage

```sh
jpsubs "/path/to/Show"                 # every video in the folder, recursively
jpsubs episode.mkv                     # one file
jpsubs --dry-run "/path/to/Show"       # show which source each video would use
jpsubs episode.mkv --subs download.srt # use a downloaded subtitle file, retimed
jpsubs --whisper-only episode.mkv      # ignore existing subtitles
jpsubs --force episode.mkv             # redo; the old .ja.srt is kept as .ja.srt.bak
jpsubs --model large-v3 episode.mkv    # slower model, similar accuracy
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

Measured on one episode against human-made Japanese subtitles: about 90% of the subtitle text is
recovered, line starts are typically within 0.3 s, and an episode takes 15 to 40 seconds on an
RTX 5070. Names, songs and overlapping speech are where it goes wrong, so treat generated lines as
a listening aid. When a human-made file exists (for example from Jimaku), `--subs` gives better text.

`kotoba-whisper-v2.0-faster` crashes with this setup and is not supported.

## Development

```sh
uv run pytest
uv tool install --force -e .   # reinstall the jpsubs command after dependency changes
```

Requires `ffmpeg`, an NVIDIA GPU (or `--device cpu`), and optionally `alass-cli` for retiming.
