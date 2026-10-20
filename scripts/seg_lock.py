"""Room lock: paste the empty room plate back over everything except the people.

Every keyframe plate then has a pixel-identical room, whatever the edit model did to it.
Mask = union of the person-segmentation masks and |image - empty| > 40, closed, net grown ~20 px, feathered.
Anything a person touches (a cushion under a hand) is kept from the cast.

usage: python seg_lock.py <empty_room.png> <out_dir> <cast1.png> [cast2.png ...]
       writes <name>_seg.png and <name>_segmask.png
Set YOLO_SEG to the path of a person-segmentation checkpoint (person_yolov8m-seg.pt was used)."""
import os, sys
import numpy as np
from PIL import Image, ImageChops, ImageFilter
from ultralytics import YOLO

MODEL = os.environ.get("YOLO_SEG", "person_yolov8m-seg.pt")
EMPTY, OUT, *IMGS = sys.argv[1:]
os.makedirs(OUT, exist_ok=True)
yolo = YOLO(MODEL)
for p in IMGS:
    im = Image.open(p).convert("RGB")
    empty = Image.open(EMPTY).convert("RGB").resize(im.size, Image.LANCZOS)
    r = yolo(np.array(im), conf=0.3, retina_masks=True, verbose=False)[0]
    m = np.zeros((im.size[1], im.size[0]), np.uint8)
    if r.masks is not None:
        for mk in r.masks.data.cpu().numpy():
            mk = np.array(Image.fromarray((mk * 255).astype(np.uint8)).resize(im.size))
            m = np.maximum(m, mk)
    n = 0 if r.masks is None else len(r.masks.data)
    # union with the |image - empty| > 40 mask: the segmenter can miss a notch of a limb
    diff = np.array(ImageChops.difference(im, empty).convert("L").filter(ImageFilter.MedianFilter(9)))
    m = np.maximum(m, np.where(diff > 40, 255, 0).astype(np.uint8))
    mask = Image.fromarray(m)
    for f in (ImageFilter.MaxFilter(41), ImageFilter.MaxFilter(41), ImageFilter.MaxFilter(41),
              ImageFilter.MinFilter(41), ImageFilter.MinFilter(41)):
        mask = mask.filter(f)                             # close holes, net grow ~20 px
    mask = mask.filter(ImageFilter.GaussianBlur(10))
    base = os.path.join(OUT, os.path.splitext(os.path.basename(p))[0])
    Image.composite(im, empty, mask).save(base + "_seg.png")
    mask.save(base + "_segmask.png")
    print(base + "_seg.png", "people:", n)
