#!/usr/bin/env python3
"""Synthesize per-scene narration via edge-tts, probe durations, emit timings.json."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # video/
PUB = ROOT / "public"
PUB.mkdir(exist_ok=True)

script = json.loads((Path(__file__).parent / "script.json").read_text(encoding="utf-8"))
voice = script["voice"]

timings = []
for sc in script["scenes"]:
    sid, text = sc["id"], sc["text"]
    mp3 = PUB / f"{sid}.mp3"
    cmd = ["edge-tts", "--voice", voice, "--text", text, "--write-media", str(mp3)]
    ok = False
    for attempt in range(4):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and mp3.exists() and mp3.stat().st_size > 1000:
            ok = True
            break
        import time
        time.sleep(2 + attempt * 2)
    if not ok:
        print(f"FAIL {sid}: {r.stderr[:400]}", file=sys.stderr)
        sys.exit(1)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(mp3)],
        capture_output=True, text=True).stdout.strip())
    timings.append({"id": sid, "audio": f"{sid}.mp3", "audioDur": round(dur, 3)})
    print(f"{sid}: {dur:.2f}s")

out = ROOT / "src" / "timings.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {out}")
