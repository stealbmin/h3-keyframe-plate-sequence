"""Render a keyframe-plate sequence (arm K) or the last-frame chain control (arm C) with MiniMax H3 FL2VA.

K: clip k uses first_frame = P(k-1) and last_frame = P(k), so neighbouring clips share a plate.
C: clip 1 starts from P0; every later clip starts from the EXACT last frame of the previous clip
   (frame index from ffprobe -count_frames, md5 logged) and has no end pin.

usage: python render_clips.py <example_dir> <arm K|C> <seed> [seed ...]
  <example_dir> holds plates/P0.png .. plates/Pn.png and prompts.json ({"prompts": [...one per clip...]}).
  Clips are written to <example_dir>/clips/<arm>_s<seed>_c<k>_00001_.mp4.
Set COMFY_URL for a remote server (default http://127.0.0.1:8188). The seed of clip k is seed + k - 1."""
import hashlib, json, os, subprocess, sys
from comfy_client import fetch, run, upload

HERE = os.path.dirname(os.path.abspath(__file__))
EX, ARM, *SEEDS = sys.argv[1:]
assert ARM in ("K", "C") and SEEDS, __doc__
cfg = json.load(open(os.path.join(EX, "prompts.json"), encoding="utf-8"))
PROMPTS = cfg["prompts"]
W, H, LENGTH = cfg.get("width", 864), cfg.get("height", 1152), cfg.get("length", 243)
OUT = os.path.join(EX, "clips")
os.makedirs(OUT, exist_ok=True)
base = json.load(open(os.path.join(HERE, "..", "graph", "h3_fl2va_api.json"), encoding="utf-8"))
tag = os.path.basename(os.path.abspath(EX))
PL = [upload(os.path.join(EX, "plates", f"P{k}.png"), f"{tag}_P{k}.png") for k in range(len(PROMPTS) + 1)]


def last_frame(mp4, png):
    n = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_read_frames", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip())
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mp4, "-vf", f"select=eq(n\\,{n - 1})", "-fps_mode", "passthrough",
                    "-update", "1", "-frames:v", "1", png], check=True)
    return n, hashlib.md5(open(png, "rb").read()).hexdigest()


def clip(seed, k, first, last=None):
    g = json.loads(json.dumps(base))
    g["60"]["inputs"]["image"] = first
    g["104"]["inputs"].update({"prompt": PROMPTS[k], "width": W, "height": H, "length": LENGTH})
    if last:
        g["62"] = {"class_type": "LoadImage", "inputs": {"image": last}}
        g["104"]["inputs"]["last_frame"] = ["62", 0]
    g["15"]["inputs"]["noise_seed"] = seed + k
    g["92"]["inputs"]["filename_prefix"] = f"keyframe_{tag}/{ARM}_s{seed}_c{k + 1}"
    files, secs = run(g)
    p = [x for x in fetch(files, OUT) if x.endswith(".mp4")][0]
    print(json.dumps({"arm": ARM, "seed": seed, "clip": k + 1, "file": os.path.basename(p), "secs": secs}), flush=True)
    return p


for s in map(int, SEEDS):
    first = PL[0]
    for k in range(len(PROMPTS)):
        if ARM == "K":
            clip(s, k, PL[k], PL[k + 1])
        else:
            p = clip(s, k, first)
            png = p.replace("_00001_.mp4", "_last.png")
            n, md5 = last_frame(p, png)
            print(json.dumps({"handoff": os.path.basename(png), "frame": n - 1, "md5": md5}), flush=True)
            first = upload(png, f"{tag}_{os.path.basename(png)}")
