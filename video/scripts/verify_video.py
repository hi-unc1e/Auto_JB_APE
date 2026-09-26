#!/usr/bin/env python3
"""Mechanical verification of the rendered video.

Checks: duration vs timings, audio stream + loudness, and one midpoint frame
per scene is non-blank and matches the light theme.
"""
import json
import subprocess
import sys
from pathlib import Path

VID = Path(sys.argv[1] if len(sys.argv) > 1 else "out/AutoAPE_demo.mp4")
ROOT = Path(__file__).resolve().parent.parent
FPS = 30
TAIL = 0.9

fail = 0

def check(name, ok, detail=""):
    global fail
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        fail = 1

# 1. container facts
probe = json.loads(subprocess.run(
    ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(VID)],
    capture_output=True, text=True).stdout)
dur = float(probe["format"]["duration"])
streams = probe["streams"]
video = [s for s in streams if s["codec_type"] == "video"][0]
audio = [s for s in streams if s["codec_type"] == "audio"]

check("video stream 1280x720", video["width"] == 1280 and video["height"] == 720,
      f'{video["width"]}x{video["height"]}')
check("has audio stream", len(audio) > 0, audio[0]["codec_name"] if audio else "none")

# 2. expected duration from timings
timings = json.loads((ROOT / "src" / "timings.json").read_text())
expected = sum(t["audioDur"] + TAIL for t in timings)
check("duration ≈ expected", abs(dur - expected) < 1.5, f"{dur:.2f}s vs {expected:.2f}s")

# 3. loudness (narration present)
vol = subprocess.run(
    ["ffmpeg", "-i", str(VID), "-af", "volumedetect", "-f", "null", "-"],
    capture_output=True, text=True).stderr
mean_line = [l for l in vol.splitlines() if "mean_volume" in l]
mean_db = float(mean_line[0].split("mean_volume:")[1].replace("dB", "").strip()) if mean_line else -99
check("audio not silent", mean_db > -45, f"mean {mean_db} dB")

# 4. per-scene midpoint frames: non-blank + light theme
from PIL import Image
import statistics
cursor = 0.0
for t in timings:
    mid = cursor + (t["audioDur"] + TAIL) / 2
    cursor += t["audioDur"] + TAIL
    out = f"/tmp/vframe_{t['id']}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", str(mid), "-i", str(VID),
         "-frames:v", "1", out], check=True)
    im = Image.open(out).convert("L")
    px = list(im.getdata())
    mean = sum(px) / len(px)
    std = statistics.pstdev(px)
    check(
        f"{t['id']} mid-frame non-blank",
        std > 8 and 120 < mean < 250,
        f"mean={mean:.0f} std={std:.0f}",
    )

sys.exit(fail)
