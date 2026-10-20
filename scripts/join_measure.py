"""Join each arm/seed into one sequence and measure it.

JOIN: frame 0 of every clip after the first duplicates the shared plate (K) or the hand-off frame (C), so it is dropped
      and 1/24 s of that clip's audio is trimmed. Reported as the boundary step / that clip's median frame step.
SPLICE: a per-frame grey RMS step > 3x the clip's median whose neighbours (+/-2 frames) stay below 2x. An isolated
      spike is a hard cut; a run of elevated steps is fast motion. Look at the frames around a spike before acting.
ROOM DRIFT: mean |frame - empty plate| over a region no person reaches (default: the top 170 rows at 432x576),
      on the last frame of the last clip, plus that region's luma and the whole frame's near-black share.

usage: python join_measure.py <example_dir> <arms, e.g. KC> <seed> [seed ...] [--rows N]
  reads <example_dir>/clips/, writes <example_dir>/joined/ and <example_dir>/measure.json"""
import json, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image

args = sys.argv[1:]
ROWS = 170
if "--rows" in args:
    i = args.index("--rows"); ROWS = int(args[i + 1]); del args[i:i + 2]
EX, ARMS, *SEEDS = args
D = Path(EX)
C = D / "clips"
J = D / "joined"; J.mkdir(exist_ok=True)
N = len(json.load(open(D / "prompts.json", encoding="utf-8"))["prompts"])
E = np.asarray(Image.open(D / "plates/room_empty.png").convert("RGB").resize((432, 576)), np.float32)
R = (slice(0, ROWS), slice(0, 432))


def frames(f):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-vf", "scale=432:576", "-fps_mode", "passthrough",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, 576, 432, 3).astype(np.float32)


def join(fs, out):
    fc = "[0:v]setpts=PTS-STARTPTS[v0];[0:a]asetpts=PTS-STARTPTS[a0];"
    for k in range(1, len(fs)):
        fc += (f"[{k}:v]trim=start_frame=1,setpts=PTS-STARTPTS[v{k}];"
               f"[{k}:a]atrim=start=0.0416667,asetpts=PTS-STARTPTS[a{k}];")
    fc += "".join(f"[v{k}][a{k}]" for k in range(len(fs))) + f"concat=n={len(fs)}:v=1:a=1[v][a]"
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + sum([["-i", str(f)] for f in fs], []) +
                   ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k", "-map_metadata", "-1", str(out)], check=True)


res = {}
for s in SEEDS:
    for arm in ARMS:
        fs = [C / f"{arm}_s{s}_c{k}_00001_.mp4" for k in range(1, N + 1)]
        join(fs, J / f"{arm}_s{s}.mp4")
        splices, joins, prev_last = [], [], None
        for k, f in enumerate(fs, 1):
            a = frames(f); g = a.mean(3)
            d = np.sqrt(((g[1:] - g[:-1]) ** 2).mean((1, 2))); m = np.median(d)
            for i in np.where(d > 3 * m)[0]:
                nb = [d[j] for j in (i - 2, i - 1, i + 1, i + 2) if 0 <= j < len(d)]
                if max(nb) < 2 * m:
                    splices.append(f"c{k}@f{i + 1}:{d[i] / m:.1f}x")
            if prev_last is not None:
                joins.append(round(float(np.sqrt(((g[0] - prev_last) ** 2).mean()) / m), 2))
            prev_last = g[-1]
            if k == N:
                end = a[-1]
                res[f"{arm}{s}"] = {
                    "splices": splices, "joins_x_median": joins,
                    "end_room_MAE": round(float(np.abs(end[R] - E[R]).mean()), 1),
                    "end_room_luma": round(float(end[R].mean()), 1),
                    "end_black%": round(float(100 * (end.mean(2) < 30).mean()), 1)}
        print(f"{arm}{s}", res[f"{arm}{s}"], flush=True)
json.dump(res, open(D / "measure.json", "w"), indent=1)
