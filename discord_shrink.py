"""
Discord Shrink - squeeze videos, images, zips and other files under a size limit.

Videos  -> two-pass H.264/AAC MP4 aimed at the exact size budget (needs ffmpeg).
Images  -> highest JPEG/WebP quality that fits, only shrinking resolution if it must.
Zips    -> repacked at maximum (lossless) compression; split into parts if still too big.
Other   -> zipped losslessly; split into parts if still too big.

Usage:
    python discord_shrink.py                 # opens the window
    python discord_shrink.py FILE [FILE...]  # compress from the command line
    python discord_shrink.py --limit 10 FILE # use a different limit (MB)
"""

import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

DEFAULT_LIMIT_MB = 20
SAFETY = 0.97  # aim a bit under the limit so container overhead never pushes us over

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
ZIP_EXTS = {".zip"}

HEIGHT_LADDER = [2160, 1440, 1080, 900, 720, 576, 540, 480, 432, 360, 288, 240]


def mb(n):
    return f"{n / 1_000_000:.2f} MB"


# ---------------------------------------------------------------- ffmpeg

def find_tool(name):
    """Look for ffmpeg/ffprobe on PATH, next to this script, and in winget's link folder."""
    exe = name + (".exe" if os.name == "nt" else "")
    here = Path(__file__).resolve().parent
    candidates = [shutil.which(name), here / exe, here / "ffmpeg" / "bin" / exe]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links" / exe)
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if pkgs.is_dir():
            candidates.extend(pkgs.glob(f"*FFmpeg*/**/bin/{exe}"))
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
ACTIVE = {"proc": None}  # the ffmpeg currently running, so the window can stop it on close


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed:\n{tail}")
    return p.stdout


def run_with_progress(cmd, duration, progress, start, span):
    """Run ffmpeg, reporting start..start+span (0-1) through progress() as it works."""
    if not progress:
        return run(cmd)
    cmd = [cmd[0], "-progress", "pipe:1", "-nostats", "-loglevel", "error"] + cmd[1:]
    with tempfile.TemporaryFile("w+") as err:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True, creationflags=NO_WINDOW)
        ACTIVE["proc"] = p
        for line in p.stdout:
            key, _, val = line.strip().partition("=")
            if key == "out_time_us" and val.isdigit():
                progress(start + span * min(1.0, int(val) / 1e6 / duration))
        if p.wait() != 0:
            err.seek(0)
            tail = "\n".join(err.read().strip().splitlines()[-8:])
            raise RuntimeError(f"ffmpeg failed:\n{tail}")


def probe(ffprobe, path):
    out = run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(out)
    duration = float(info["format"].get("duration", 0) or 0)
    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in info["streams"])
    if not v or duration <= 0:
        raise RuntimeError("Couldn't read the video's length or picture.")
    w, h = int(v["width"]), int(v["height"])
    rot = str(v.get("tags", {}).get("rotate", "0"))
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = str(sd["rotation"])
    if rot.lstrip("-") in ("90", "270"):
        w, h = h, w
    num, _, den = v.get("avg_frame_rate", "30/1").partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    if not 1 <= fps <= 240:
        fps = 30.0
    return duration, w, h, fps, has_audio


def plan_video(duration, w, h, fps, has_audio, target_bytes, downscale=False):
    total_kbps = target_bytes * 8 / 1000 / duration
    if not has_audio:
        audio_kbps = 0
    elif total_kbps > 1500:
        audio_kbps = 160
    elif total_kbps > 600:
        audio_kbps = 128
    elif total_kbps > 250:
        audio_kbps = 96
    else:
        audio_kbps = 64
    video_kbps = total_kbps * 0.98 - audio_kbps
    if video_kbps < 60:
        raise RuntimeError(
            f"The video is too long ({duration / 60:.1f} min) to look watchable in this size. "
            "Trim it or split it into shorter clips first.")

    # Frame rate is always kept. Resolution is kept too unless downscaling was asked for.
    out_fps = fps

    # ~0.05 bits per pixel per frame keeps H.264 (preset slow) looking clean; drop resolution until we get there
    max_pixels = video_kbps * 1000 / (out_fps * 0.05)
    out_h = h
    if downscale and w * h > max_pixels:
        out_h = HEIGHT_LADDER[-1]
        for lh in HEIGHT_LADDER:
            if lh <= h and (w * lh / h) * lh <= max_pixels:
                out_h = lh
                break
    return video_kbps, audio_kbps, out_fps, min(out_h, h)


def compress_video(path, target_bytes, log, downscale=False, progress=None):
    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg isn't installed. Run Setup.bat once, then try again.")

    duration, w, h, fps, has_audio = probe(ffprobe, path)
    out = path.with_name(path.stem + "_discord.mp4")
    budget = target_bytes
    for attempt in range(1, 4):
        vk, ak, ofps, oh = plan_video(duration, w, h, fps, has_audio, budget, downscale)
        log(f"  {w}x{h} @ {fps:.0f}fps, {duration:.1f}s -> {oh}p @ {ofps:.0f}fps, "
            f"video {vk:.0f} kbps, audio {ak} kbps (pass {attempt})")
        vf = []
        if oh < h:
            vf.append(f"scale=-2:{oh}:flags=lanczos")
        with tempfile.TemporaryDirectory() as tmp:
            passlog = os.path.join(tmp, "pass")
            common = [ffmpeg, "-y", "-hide_banner", "-i", str(path), "-map", "0:v:0",
                      "-c:v", "libx264", "-preset", "slow", "-b:v", f"{vk:.0f}k",
                      "-pix_fmt", "yuv420p", "-passlogfile", passlog]
            if vf:
                common += ["-vf", ",".join(vf)]
            log("  analysing (1/2)...")
            run_with_progress(common + ["-pass", "1", "-an", "-f", "null", os.devnull],
                              duration, progress, 0.0, 0.5)
            log("  encoding (2/2)...")
            audio = ["-map", "0:a:0?", "-c:a", "aac", "-b:a", f"{ak}k"] if has_audio else ["-an"]
            run_with_progress(common + ["-pass", "2"] + audio + ["-movflags", "+faststart", str(out)],
                              duration, progress, 0.5, 0.5)
        size = out.stat().st_size
        if size <= target_bytes:
            return out
        budget = budget * target_bytes / size * 0.97
        log(f"  came out at {mb(size)}, retrying a little smaller...")
    raise RuntimeError("Couldn't get the video under the limit.")


# ---------------------------------------------------------------- images

def compress_image(path, target_bytes, log):
    from PIL import Image, ImageOps

    img = Image.open(path)
    frames = getattr(img, "n_frames", 1)
    if frames > 1 and path.suffix.lower() == ".gif":
        return compress_gif(img, path, target_bytes, log)
    img = ImageOps.exif_transpose(img)

    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    if has_alpha:
        img, fmt, ext = img.convert("RGBA"), "WEBP", ".webp"
    else:
        img, fmt, ext = img.convert("RGB"), "JPEG", ".jpg"

    # Lossless PNG first if the original was PNG and the optimised copy already fits
    if path.suffix.lower() == ".png":
        buf = io.BytesIO()
        Image.open(path).save(buf, "PNG", optimize=True)
        if buf.tell() <= target_bytes:
            out = path.with_name(path.stem + "_discord.png")
            out.write_bytes(buf.getvalue())
            log("  fits as lossless PNG")
            return out

    def encode(im, q):
        buf = io.BytesIO()
        if fmt == "JPEG":
            im.save(buf, fmt, quality=q, optimize=True, progressive=True, subsampling=0 if q >= 90 else 2)
        else:
            im.save(buf, fmt, quality=q, method=6)
        return buf.getvalue()

    scale = 1.0
    while True:
        im = img if scale == 1.0 else img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
        lo, hi, best = 70, 95, None
        while lo <= hi:  # highest quality that fits
            q = (lo + hi) // 2
            data = encode(im, q)
            if len(data) <= target_bytes:
                best, lo = (q, data), q + 1
            else:
                hi = q - 1
        if best:
            out = path.with_name(path.stem + "_discord" + ext)
            out.write_bytes(best[1])
            log(f"  {fmt} quality {best[0]}, {im.width}x{im.height}")
            return out
        scale *= 0.85


def compress_gif(img, path, target_bytes, log):
    from PIL import Image, ImageSequence

    frames = [f.copy() for f in ImageSequence.Iterator(img)]
    durations = [f.info.get("duration", img.info.get("duration", 100)) for f in frames]
    scale = 1.0
    while True:
        sized = frames if scale == 1.0 else [
            f.convert("RGBA").resize((max(1, round(f.width * scale)), max(1, round(f.height * scale))), Image.LANCZOS)
            for f in frames]
        buf = io.BytesIO()
        sized[0].save(buf, "GIF", save_all=True, append_images=sized[1:], optimize=True,
                      duration=durations, loop=img.info.get("loop", 0), disposal=2)
        size = buf.tell()
        if size <= target_bytes:
            out = path.with_name(path.stem + "_discord.gif")
            out.write_bytes(buf.getvalue())
            log(f"  GIF {sized[0].width}x{sized[0].height}, {len(frames)} frames")
            return out
        scale *= max(0.5, min(0.92, math.sqrt(target_bytes / size) * 0.97))


# ---------------------------------------------------------------- zips & everything else (lossless)

def repack_zip(src, dst):
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            item.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def compress_lossless(path, limit_bytes, log):
    out = path.with_name((path.name if path.is_dir() else path.stem) + "_discord.zip")
    if path.is_dir():
        log("  zipping folder at maximum compression...")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in sorted(path.rglob("*")):
                z.write(f, f.relative_to(path.parent))
    elif path.suffix.lower() in ZIP_EXTS:
        log("  repacking zip at maximum compression...")
        repack_zip(path, out)
    else:
        log("  zipping at maximum compression...")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.write(path, path.name)

    size = out.stat().st_size
    if path.suffix.lower() in ZIP_EXTS and size >= path.stat().st_size:
        shutil.copyfile(path, out)  # repacking didn't help; keep the original bytes
        size = out.stat().st_size
    if size <= limit_bytes:
        return out

    log(f"  still {mb(size)} - splitting into parts (nothing is lost, rejoin with 7-Zip or JOIN.bat)")
    folder = path.with_name(path.stem + "_discord_parts")
    folder.mkdir(exist_ok=True)
    part_size = int(limit_bytes)
    names = []
    with open(out, "rb") as f:
        i = 1
        while chunk := f.read(part_size):
            name = f"{out.name}.{i:03d}"
            (folder / name).write_bytes(chunk)
            names.append(name)
            i += 1
    out.unlink()
    join = "copy /b " + "+".join(f'"{n}"' for n in names) + f' "{out.name}"'
    (folder / "JOIN.bat").write_text(f'@echo off\ncd /d "%~dp0"\n{join}\necho Done: {out.name}\npause\n')
    log(f"  {len(names)} parts in {folder.name}\\")
    return folder


# ---------------------------------------------------------------- driver

def shrink(path, limit_mb, log=print, downscale=False, progress=None):
    path = Path(path)
    limit_bytes = limit_mb * 1_000_000
    target = limit_bytes * SAFETY
    if path.is_dir():
        log(f"{path.name}\\  (folder)")
        out = compress_lossless(path, target, log)
        log(f"  done -> {out.name}")
        return out
    size = path.stat().st_size
    log(f"{path.name}  ({mb(size)})")
    if size <= target:
        log("  already under the limit - nothing to do")
        return path
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        out = compress_video(path, target, log, downscale, progress)
    elif ext in IMAGE_EXTS:
        out = compress_image(path, target, log)
    else:
        out = compress_lossless(path, target, log)
    if out.is_file():
        log(f"  done -> {out.name}  ({mb(out.stat().st_size)})")
    else:
        log(f"  done -> {out.name}\\")
    return out


def run_cli(files, limit_mb, downscale=False):
    failures = 0
    for f in files:
        try:
            shrink(f, limit_mb, downscale=downscale)
        except Exception as e:
            failures += 1
            print(f"  ERROR: {e}")
        print()
    return 1 if failures else 0


def run_gui(limit_mb):
    import gui  # gui.py next to this file
    gui.run(sys.modules[__name__], limit_mb)


def main():
    ap = argparse.ArgumentParser(description="Shrink files to fit Discord's upload limit.")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--limit", type=float, default=DEFAULT_LIMIT_MB, help="size limit in MB (default 20)")
    ap.add_argument("--downscale", action="store_true",
                    help="allow lowering video resolution when the bitrate gets very low")
    args = ap.parse_args()
    if args.files:
        sys.exit(run_cli(args.files, args.limit, args.downscale))
    run_gui(args.limit)


if __name__ == "__main__":
    main()
