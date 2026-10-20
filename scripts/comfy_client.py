"""Minimal ComfyUI API client. Works against the local server or a tunnelled pod:
set COMFY_URL (default http://127.0.0.1:8188; a pod tunnel is usually http://127.0.0.1:8189).
Images are uploaded through /upload/image and results fetched through /view, so nothing depends on
the server's own input/output folders."""
import json, os, time, uuid, urllib.error, urllib.parse, urllib.request

URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")


def upload(path, name=None):
    """Upload a local image into the server's input folder; returns the name LoadImage should use."""
    name = name or os.path.basename(path)
    b = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    body = (f'--{b}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f'Content-Type: image/png\r\n\r\n').encode() + data + \
           (f'\r\n--{b}\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n--{b}--\r\n').encode()
    req = urllib.request.Request(URL + "/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
    r = json.load(urllib.request.urlopen(req))
    return f'{r["subfolder"]}/{r["name"]}' if r.get("subfolder") else r["name"]


def run(graph, poll=5):
    """Queue an API-format graph, wait for it, return (list of output file records, seconds)."""
    req = urllib.request.Request(URL + "/prompt", json.dumps({"prompt": graph, "client_id": str(uuid.uuid4())}).encode(),
                                 {"Content-Type": "application/json"})
    try:
        pid = json.load(urllib.request.urlopen(req))["prompt_id"]
    except urllib.error.HTTPError as e:
        raise SystemExit("REJECTED " + e.read().decode()[:1500])
    t0 = time.time()
    while True:
        try:
            h = json.load(urllib.request.urlopen(f"{URL}/history/{pid}", timeout=30))
        except Exception:
            # The API can stop answering during long synchronous work. That is NOT a failed render: keep waiting.
            time.sleep(poll); continue
        if pid in h and h[pid]["status"].get("completed") is not None:
            break
        time.sleep(poll)
    st = h[pid]["status"]
    if st["status_str"] != "success":
        raise SystemExit("FAILED " + json.dumps(st)[:2500])
    files = [f for o in h[pid]["outputs"].values() for v in o.values() if isinstance(v, list)
             for f in v if isinstance(f, dict) and "filename" in f]
    return files, round(time.time() - t0)


def fetch(files, out_dir):
    """Download output files from the server into out_dir; returns local paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for f in files:
        q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                    "type": f.get("type", "output")})
        p = os.path.join(out_dir, f["filename"])
        with urllib.request.urlopen(f"{URL}/view?{q}") as r, open(p, "wb") as o:
            o.write(r.read())
        paths.append(p)
    return paths

