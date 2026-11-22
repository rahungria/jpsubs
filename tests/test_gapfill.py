from jpsubs.clean import Cue
from jpsubs.gapfill import Candidate, accept, find_gaps, merge_gaps, second_look


def test_find_gaps_ignores_windows_with_a_cue_nearby():
    windows = [(1.0, 2.0), (10.0, 11.0), (20.0, 21.0)]
    cues = [Cue(1.2, 1.8, "中"), Cue(11.3, 12.0, "すぐ後")]
    # the second window is covered by a cue starting 0.3 s after it ends
    assert find_gaps(windows, cues) == [(20.0, 21.0)]


def test_find_gaps_without_cues_returns_every_window():
    assert find_gaps([(1.0, 2.0)], []) == [(1.0, 2.0)]


def test_merge_gaps_joins_close_neighbours_only():
    gaps = [(10.0, 11.0), (11.5, 12.5), (20.0, 21.0)]
    assert merge_gaps(gaps) == [(10.0, 12.5), (20.0, 21.0)]


def test_merge_gaps_respects_the_length_cap():
    gaps = [(float(i), i + 0.8) for i in range(20)]
    merged = merge_gaps(gaps, max_len=5.0)
    assert all(end - start <= 5.0 for start, end in merged)
    assert len(merged) > 1


def test_merge_gaps_handles_overlap_and_order():
    assert merge_gaps([(5.0, 6.0), (1.0, 3.0), (2.0, 2.5)]) == [(1.0, 3.0), (5.0, 6.0)]


def test_accept():
    assert accept("くだらない", 1.5, -0.3)
    assert not accept("Thank you.", 1.5, -0.1)  # not Japanese
    assert not accept("ご視聴ありがとうございました", 3.0, -0.2)  # known invention
    assert not accept("くだらない", 1.5, -1.5)  # low confidence
    assert not accept("あ" * 40, 1.5, -0.2)  # too much text for the time


class FakeTranscriber:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def transcribe_window(self, audio, start, end):
        self.calls.append((start, end))
        return self.results.pop(0) if self.results else []


def test_second_look_fills_only_gaps_and_pads_the_window():
    windows = [(1.0, 2.0), (10.0, 11.0)]
    cues = [Cue(1.0, 2.0, "既にある")]
    fake = FakeTranscriber([[Candidate([Cue(10.1, 10.9, "くだらない")], "くだらない", -0.3)]])
    new = second_look(fake, None, windows, cues)
    assert fake.calls == [(9.5, 11.5)]
    assert [(c.start, c.text) for c in new] == [(10.1, "くだらない")]


def test_second_look_rejects_inventions_and_overlaps():
    windows = [(10.0, 11.0), (30.0, 31.0)]
    cues = [Cue(31.7, 33.0, "隣の行")]  # just outside the slack, but inside the padded clip
    fake = FakeTranscriber(
        [
            [Candidate([Cue(10.1, 10.9, "ご視聴ありがとうございました")], "ご視聴ありがとうございました", -0.2)],
            [
                Candidate([Cue(30.1, 30.9, "新しい行")], "新しい行", -0.3),
                Candidate([Cue(31.2, 31.9, "隣の行")], "隣の行", -0.3),
            ],
        ]
    )
    new = second_look(fake, None, windows, cues)
    assert [c.text for c in new] == ["新しい行"]


def test_second_look_start_is_not_negative():
    fake = FakeTranscriber([])
    second_look(fake, None, [(0.1, 1.0)], [])
    assert fake.calls == [(0.0, 1.5)]
