
import os
import sys
from encoder import _pick_encoder, _find_ffmpeg

def test_pref(pref):
    ffmpeg = _find_ffmpeg()
    cfg = {"quality": "mid", "hardware_accel": pref}
    print(f"\nTesting Preference: {pref}")
    for codec in ["h264", "h265", "vp9"]:
        try:
            enc, args = _pick_encoder(ffmpeg, codec, cfg)
            print(f"  {codec:5}: {enc}")
        except Exception as e:
            print(f"  {codec:5}: FAILED ({e})")

if __name__ == "__main__":
    for p in ["intel", "gpu", "software"]:
        test_pref(p)
