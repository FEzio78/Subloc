import numpy as np

from subloc import asr
from subloc.models import Cue

SR = 16000


def test_only_speech_without_a_line_is_listened_to_again():
    cues = [Cue(id=1, start=10.0, end=12.0, text="a"), Cue(id=2, start=20.0, end=21.0, text="b")]
    speech = [(9.0, 13.5), (15.0, 15.3), (30.0, 32.0), (32.5, 34.0)]
    pieces = asr.uncovered(speech, cues, 60.0)
    # 9.0-9.7 (before line 1, its margin) and 12.3-13.5 (after); 15.0-15.3 is too short; 30-34 heard as one piece
    assert pieces == [(9.0, 9.7), (12.3, 13.5), (30.0, 34.0)]


def test_long_quiet_stretches_are_split_for_whisper():
    pieces = asr.uncovered([(0.0, 50.0)], [], 60.0)
    assert len(pieces) == 1 and pieces[0] == (0.0, 50.0)  # one span: Whisper itself handles 30 s windows
    gaps = [(float(i), i + 0.8) for i in range(0, 40, 1)]  # many short bits close together
    assert all(b - a <= asr.RESCUE_MAX for a, b in asr.uncovered(gaps, [], 60.0))


def test_quiet_audio_is_brought_to_speech_level_but_not_beyond_30_db():
    quiet = (np.sin(np.arange(SR) / 10) * 0.003).astype(np.float32)  # about -53 dBFS
    up = asr.louder(quiet)
    assert 20 * np.log10(np.sqrt(np.mean(up**2))) > -25
    silence = np.full(SR, 1e-6, np.float32)
    assert np.abs(asr.louder(silence)).max() < 1e-4  # noise floor isn't blown up past +30 dB
    assert np.abs(asr.louder(np.ones(SR, np.float32))).max() <= 1.0
