from jpsubs.clean import (
    Cue,
    Word,
    clean_cues,
    fix_timing,
    format_timestamp,
    is_hallucination,
    looks_japanese,
    split_words,
    to_srt,
)


def words(*parts, start=0.0, step=0.5):
    out, t = [], start
    for p in parts:
        out.append(Word(t, t + step, p))
        t += step
    return out


def test_split_at_sentence_end():
    cues = split_words(words("名前を", "書くと", "死ぬ。", "まさか", "な。"))
    assert [c.text for c in cues] == ["名前を書くと死ぬ。", "まさかな。"]
    assert cues[0].start == 0.0 and cues[0].end == 1.5
    assert cues[1].start == 1.5


def test_split_on_long_pause():
    ws = [Word(0, 1, "そうか"), Word(4, 5, "なるほど")]
    assert [c.text for c in split_words(ws)] == ["そうか", "なるほど"]


def test_long_line_breaks_at_clause_near_middle():
    ws = words("あ" * 10 + "、", "い" * 10 + "、", "う" * 10)
    cues = split_words(ws, max_chars=20)
    assert [len(c.text) for c in cues] == [11, 11, 10]


def test_long_line_breaks_at_space():
    # Whisper writes a space where a subtitle would have a comma
    ws = words("あ" * 12, " " + "い" * 12)
    assert [c.text for c in split_words(ws, max_chars=20)] == ["あ" * 12, "い" * 12]


def test_long_line_without_marks_breaks_at_pause():
    ws = [Word(0, 1, "あ" * 8), Word(1, 2, "い" * 8), Word(2.5, 3.5, "う" * 8)]
    assert [c.text for c in split_words(ws, max_chars=20)] == ["あ" * 8 + "い" * 8, "う" * 8]


def test_slightly_long_line_without_marks_or_pauses_is_kept_whole():
    ws = words("あ" * 12, "い" * 12)
    assert len(split_words(ws, max_chars=20)) == 1


def test_very_long_line_is_always_broken():
    ws = words("あ" * 20, "い" * 20)
    assert len(split_words(ws, max_chars=20)) == 2


def test_stray_first_syllable_joins_the_line_after_the_pause():
    ws = [Word(17.3, 18.0, "一"), Word(28.3, 28.8, "体"), Word(28.8, 29.5, "何を")]
    cues = split_words(ws)
    assert [(c.start, c.text) for c in cues] == [(28.3, "一体何を")]


def test_short_exclamation_not_split_off():
    # a 1-2 character fragment with punctuation stays attached to what follows
    cues = split_words(words("え？", "何だって？"))
    assert [c.text for c in cues] == ["え？何だって？"]


def test_hallucination_patterns():
    assert is_hallucination("ご視聴ありがとうございました")
    assert is_hallucination("チャンネル登録お願いします")
    assert not is_hallucination("ありがとうございました")


def test_clean_drops_junk_and_hallucinations():
    cues = [
        Cue(0, 1, "  こんにちは  "),
        Cue(1, 2, "♪～"),
        Cue(2, 3, ""),
        Cue(3, 4, "ご視聴ありがとうございました"),
        Cue(5, 5, "長さゼロ"),
    ]
    assert [c.text for c in clean_cues(cues, drop_hallucinations=True)] == ["こんにちは"]
    # existing human-made subs keep such lines
    assert len(clean_cues(cues)) == 2


def test_clean_merges_layered_duplicates_and_sorts():
    cues = [Cue(2, 3, "次"), Cue(0, 1, "同じ"), Cue(0, 1.5, "同じ")]
    out = clean_cues(cues)
    assert [(c.start, c.end, c.text) for c in out] == [(0, 1.5, "同じ"), (2, 3, "次")]


def test_clean_collapses_repeat_loops():
    cues = [Cue(i * 2, i * 2 + 1, "はい") for i in range(6)] + [Cue(20, 21, "終わり")]
    out = clean_cues(cues, drop_hallucinations=True)
    assert [c.text for c in out] == ["はい", "終わり"]


def test_clean_keeps_a_line_said_twice():
    cues = [Cue(0, 1, "はい"), Cue(2, 3, "はい"), Cue(4, 5, "うん")]
    assert len(clean_cues(cues, drop_hallucinations=True)) == 3


def test_fix_timing_overlap_and_min_duration():
    cues = fix_timing([Cue(0, 0.1, "あ"), Cue(5, 30, "い"), Cue(10, 11, "う")])
    assert cues[0].end == 0.7
    assert cues[1].end == 10
    assert cues[2].end == 11


def test_looks_japanese():
    assert looks_japanese([Cue(0, 1, "こんにちは"), Cue(1, 2, "漢字")])
    assert not looks_japanese([Cue(0, 1, "Hello there"), Cue(1, 2, "General Kenobi")])
    assert not looks_japanese([])


def test_srt_output():
    assert format_timestamp(3661.5) == "01:01:01,500"
    assert format_timestamp(0.9996) == "00:00:01,000"
    srt = to_srt([Cue(1, 2.5, "一行目"), Cue(3, 4, "二行目")])
    assert srt == "1\n00:00:01,000 --> 00:00:02,500\n一行目\n\n2\n00:00:03,000 --> 00:00:04,000\n二行目\n"
