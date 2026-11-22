from pathlib import Path

from jpsubs.probe import find_sidecar_subs, load_sub_file, parse_streams, pick_audio, pick_ja_subs


def streams(*specs):
    data = {"streams": []}
    for i, (kind, codec, lang, title, disp) in enumerate(specs):
        data["streams"].append(
            {
                "index": i,
                "codec_type": kind,
                "codec_name": codec,
                "tags": {"language": lang, "title": title},
                "disposition": disp,
            }
        )
    return parse_streams(data)


def test_pick_audio_prefers_japanese_over_default():
    s = streams(
        ("video", "hevc", "", "", {}),
        ("audio", "aac", "eng", "English", {"default": 1}),
        ("audio", "aac", "jpn", "Japanese", {}),
    )
    assert pick_audio(s).index == 2


def test_pick_audio_skips_japanese_commentary():
    s = streams(
        ("audio", "aac", "jpn", "Staff Commentary", {}),
        ("audio", "aac", "jpn", "Stereo", {}),
    )
    assert pick_audio(s).index == 1


def test_pick_audio_falls_back_to_default_then_first():
    s = streams(("audio", "aac", "", "", {}), ("audio", "aac", "", "", {"default": 1}))
    assert pick_audio(s).index == 1
    assert pick_audio(streams(("audio", "aac", "und", "", {}))).index == 0
    assert pick_audio(streams(("video", "h264", "", "", {}))) is None


def test_pick_ja_subs_text_only_dialogue_first():
    s = streams(
        ("subtitle", "ass", "eng", "English", {}),
        ("subtitle", "hdmv_pgs_subtitle", "jpn", "Japanese", {}),
        ("subtitle", "ass", "jpn", "Signs & Songs", {}),
        ("subtitle", "subrip", "jpn", "Japanese", {}),
    )
    assert [x.index for x in pick_ja_subs(s)] == [3, 2]


def test_tags_are_case_insensitive():
    data = {"streams": [{"index": 0, "codec_type": "audio", "codec_name": "aac", "tags": {"LANGUAGE": "JPN"}}]}
    assert parse_streams(data)[0].lang == "jpn"


def test_find_sidecar_subs(tmp_path: Path):
    video = tmp_path / "Show - 01.mkv"
    output = tmp_path / "Show - 01.ja.srt"
    for name in ["Show - 01.mkv", "Show - 01.ja.srt", "Show - 01.srt", "Show - 01.jpn.ass", "Show - 010.srt", "Show - 02.srt"]:
        (tmp_path / name).write_text("x")
    assert [p.name for p in find_sidecar_subs(video, output)] == ["Show - 01.jpn.ass", "Show - 01.srt"]


def test_load_ass_strips_tags_drawings_and_comments(tmp_path: Path):
    ass = tmp_path / "a.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize\nStyle: Default,Arial,20\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\i1}こんにちは{\\i0}\\N世界\n"
        "Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,{\\p1}m 0 0 l 10 10{\\p0}\n"
        "Comment: 0,0:00:05.00,0:00:06.00,Default,,0,0,0,,メモ\n",
        encoding="utf-8",
    )
    cues = load_sub_file(ass)
    assert [(c.start, c.end, c.text) for c in cues] == [(1.0, 2.5, "こんにちは\n世界")]


def test_load_shift_jis_srt(tmp_path: Path):
    srt = tmp_path / "a.srt"
    srt.write_bytes("1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n".encode("shift_jis"))
    assert load_sub_file(srt)[0].text == "こんにちは"


def test_dialogue_track_order_prefers_english_dialogue():
    from jpsubs.probe import dialogue_track_order

    s = streams(
        ("subtitle", "ass", "eng", "Signs and Songs", {}),
        ("subtitle", "ass", "spa", "Spanish", {}),
        ("subtitle", "hdmv_pgs_subtitle", "eng", "English", {}),
        ("subtitle", "ass", "eng", "English", {}),
    )
    assert [x.index for x in dialogue_track_order(s)] == [3, 1, 0]


def test_dialogue_windows_skip_songs_signs_and_placed_text(tmp_path: Path):
    import pysubs2

    from jpsubs.probe import dialogue_windows

    ass = tmp_path / "a.ass"
    head = (
        "[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize\n"
        + "".join(f"Style: {n},Arial,20\n" for n in ["Default", "Show Thoughts", "Show OP", "ED romaji", "TS_Sign", "Top"])
        + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        "Dialogue: 0,0:00:05.00,0:00:06.50,Default,,0,0,0,,Spoken line",
        "Dialogue: 0,0:00:01.00,0:00:02.00,Show Thoughts,,0,0,0,,{\\i1}Inner voice",
        "Dialogue: 0,0:00:10.00,0:00:12.00,Show OP,,0,0,0,,opening song",
        "Dialogue: 0,0:00:12.00,0:00:14.00,ED romaji,,0,0,0,,ending song",
        "Dialogue: 0,0:00:15.00,0:00:16.00,TS_Sign,,0,0,0,,a sign",
        "Dialogue: 0,0:00:17.00,0:00:18.00,Default,,0,0,0,,{\\pos(100,200)}placed text",
        "Dialogue: 0,0:00:19.00,0:00:20.00,Default,,0,0,0,,{\\k20}ka{\\k30}ra",
        "Dialogue: 0,0:00:21.00,0:00:21.10,Default,,0,0,0,,flash",
        "Dialogue: 0,0:00:22.00,0:00:23.00,Top,,0,0,0,,{\\an8}Spoken, shown at the top",
        "Comment: 0,0:00:30.00,0:00:31.00,Default,,0,0,0,,note to self",
    ]
    ass.write_text(head + "\n".join(lines) + "\n", encoding="utf-8")
    assert dialogue_windows(pysubs2.load(str(ass))) == [(1.0, 2.0), (5.0, 6.5), (22.0, 23.0)]
