"""Compose a two-person keyframe plate from two edit-model casts that share one empty room.

A = person A's room-locked solo plate (seg_lock.py output). B = a "duo" cast: person B added INTO A's locked plate,
so the edit model keeps B clear of A. The output is: empty room <- A taken from A's plate <- B taken from the duo cast.
B is the detected person who does NOT overlap A, and B's mask never covers A's area, so the duo render's redrawn copy
of A cannot overwrite the locked A.

Per person: the YOLO person mask, unioned with |cast - empty| > 40 inside that person's box grown 60 px (catches thin
parts the segmenter misses without importing the cast's drifted room), closed, grown ~15 px and feathered.

usage: python compose.py <empty_room.png> <out.png> <A_locked.png> <B_duo.png>
       also writes <out>_masks.png (red = A, green = B) for checking overlap
Set YOLO_SEG to the path of a person-segmentation checkpoint (person_yolov8m-seg.pt was used)."""
import os, sys
import numpy as np
from PIL import Image, ImageChops, ImageFilter
from ultralytics import YOLO

MODEL = os.environ.get("YOLO_SEG", "person_yolov8m-seg.pt")
EMPTY, OUT, A, B = sys.argv[1:5]
yolo = YOLO(MODEL)


def person_mask(path, empty, avoid=None):
    im = Image.open(path).convert("RGB")
    r = yolo(np.array(im), conf=0.3, retina_masks=True, verbose=False)[0]
    assert r.masks is not None, f"no person in {path}"
    ms = [np.array(Image.fromarray((m * 255).astype(np.uint8)).resize(im.size)) for m in r.masks.data.cpu().numpy()]
    if avoid is None:
        m = max(ms, key=lambda x: (x > 127).sum())
    else:  # duo cast: take the person who is NOT standing where A is
        av = np.asarray(avoid) > 64
        m = min(ms, key=lambda x: ((x > 127) & av).sum() / max((x > 127).sum(), 1))
    ys, xs = np.where(m > 127)
    y0, y1, x0, x1 = max(ys.min() - 60, 0), ys.max() + 60, max(xs.min() - 60, 0), xs.max() + 60
    diff = np.array(ImageChops.difference(im, empty).convert("L").filter(ImageFilter.MedianFilter(9)))
    box = np.zeros_like(m); box[y0:y1, x0:x1] = 1
    keep = (diff > 40) & (box > 0)
    if avoid is not None:  # never let B's redrawn copy of A overwrite the locked A
        keep &= ~(np.asarray(avoid) > 32)
    m = np.maximum(m, np.where(keep, 255, 0).astype(np.uint8))
    mask = Image.fromarray(m)
    for f in (ImageFilter.MaxFilter(31), ImageFilter.MaxFilter(31), ImageFilter.MinFilter(31)):
        mask = mask.filter(f)
    return im, mask.filter(ImageFilter.GaussianBlur(8)), len(ms)


empty = Image.open(EMPTY).convert("RGB")
ia, ma, na = person_mask(A, empty.resize(Image.open(A).size))
empty = empty.resize(ia.size, Image.LANCZOS)
ib, mb, nb = person_mask(B, empty, avoid=ma)
out = Image.composite(ia, empty, ma)
out = Image.composite(ib, out, mb)
out.save(OUT)
ov = (np.asarray(ma) > 64) & (np.asarray(mb) > 64)
Image.merge("RGB", (ma, mb, Image.new("L", ma.size))).save(os.path.splitext(OUT)[0] + "_masks.png")
print(OUT, f"people in casts: {na}/{nb}", f"mask overlap px: {int(ov.sum())}")
