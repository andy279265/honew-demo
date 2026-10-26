#!/usr/bin/env python3
"""One-time inspection of public Vimeo videos, on an isolated Git branch.

Downloads neither original nor derived footage into the production site.
Writes low-resolution contact sheets encoded as text for visual review.
"""
import base64
import io
import json
import os
import subprocess
import tempfile
import traceback
from pathlib import Path
import yt_dlp
from PIL import Image, ImageDraw

IDS = ["1091770143", "1091770158", "1091770222", "1093149030", "1150916069", "1091770174", "1091769722"]
output = Path("audit-outros")
output.mkdir(parents=True, exist_ok=True)
report = {}
for video_id in IDS:
    entry = {"id": video_id}
    print("Inspecting", video_id, flush=True)
    try:
        options = {"quiet": True, "no_warnings": True, "skip_download": True,
                   "noplaylist": True, "socket_timeout": 12}
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info("https://vimeo.com/" + video_id, download=False)
        duration = float(info.get("duration") or 0)
        formats = [f for f in info.get("formats", []) if f.get("url") and
                   (f.get("vcodec") or "none") != "none"]
        chosen = next((f for f in sorted(formats, key=lambda x: abs((x.get("height") or 480) - 480))
                       if f.get("protocol") in ("https", "http") and f.get("ext") in ("mp4", "mov")), None)
        if not chosen:
            chosen = next((f for f in formats if f.get("protocol") in ("m3u8_native", "m3u8")), None)
        entry.update({"duration": duration, "title": info.get("title"), "format": chosen.get("format_id") if chosen else None})
        if not chosen or duration <= 1:
            entry["error"] = "No stream available for frame inspection"
        else:
            with tempfile.TemporaryDirectory() as temp:
                temp = Path(temp)
                headers = chosen.get("http_headers") or {}
                header_str = "".join(f"{k}: {v}\r\n" for k,v in headers.items())
                start = max(0, duration - 15)
                cmd = ["ffmpeg", "-loglevel", "error", "-y"]
                if header_str:
                    cmd.extend(["-headers", header_str])
                cmd.extend(["-ss", str(start), "-i", chosen["url"], "-t", str(min(15, duration)),
                            "-vf", "fps=1/2,scale=360:-2", "-frames:v", "8",
                            str(temp / "frame%02d.jpg")])
                cmdrun = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
                jpgs = sorted(temp.glob("frame*.jpg"))
                entry["frames"] = len(jpgs)
                if not jpgs:
                    entry["error"] = "ffmpeg failed: " + cmdrun.stderr[-500:]
                else:
                    ims = []
                    for pos, filename in enumerate(jpgs):
                        with Image.open(filename) as im:
                            im = im.convert("RGB")
                            canvas = Image.new("RGB", (380, 250), "#eeeeee")
                            im.thumbnail((360, 220))
                            canvas.paste(im, ((380-im.width)//2, 5))
                            draw = ImageDraw.Draw(canvas)
                            label=f"~{start+pos*2:.1f}s / {duration:.1f}s"
                            draw.text((12, 228), label, fill="black")
                            ims.append(canvas)
                    sheet=Image.new("RGB",(380*4,250*2),"white")
                    for n,im in enumerate(ims):sheet.paste(im,((n%4)*380,(n//4)*250))
                    with io.BytesIO() as buf:
                        sheet.save(buf,format="JPEG",quality=70,optimize=True)
                        encoded=base64.b64encode(buf.getvalue()).decode("ascii")
                    (output / f"{video_id}.jpg.b64").write_text(encoded)
                    entry["contact_sheet"]="audit-outros/"+video_id+".jpg.b64"
    except Exception as exc:
        entry["error"] = (type(exc).__name__ + ": " + str(exc))[:700]
    report[video_id] = entry
    print(video_id, json.dumps(entry, ensure_ascii=False), flush=True)
(output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
print("Done: ", json.dumps(report,ensure_ascii=False))
