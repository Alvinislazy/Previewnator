"""
Previewnator — FFmpeg encoding pipeline.
Converts each Sequence to a temp video with overlays, then concatenates.
"""
import os
import sys
import shutil
import subprocess
import tempfile
import datetime
import re
import concurrent.futures
import threading
from sequence import Sequence


# ── Encoder selection ──────────────────────────────────────────────────────────

def _find_ffmpeg() -> str:
    """Return the path to the ffmpeg executable."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    # Common install locations on Windows and local bin download
    local_bin = os.path.join(os.path.dirname(__file__), "bin", "ffmpeg.exe")
    for candidate in [
        local_bin,
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return _ensure_ffmpeg(local_bin)

def _ensure_ffmpeg(ffmpeg_exe: str) -> str:
    """Ensure ffmpeg is available, downloading it if necessary."""
    import urllib.request
    import zipfile
    
    py_bin_dir = os.path.dirname(ffmpeg_exe)
    print("[Previewnator] FFmpeg not found. Attempting to download static build ...")
    os.makedirs(py_bin_dir, exist_ok=True)
    
    # URL for a reliable static build (Gyan.dev)
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    zip_path = os.path.join(py_bin_dir, "ffmpeg.zip")
    
    def _progress(count, block_size, total_size):
        if total_size > 0:
            percent = min(100, count * block_size * 100 / total_size)
            print(f"\r  Downloading: {percent:.1f}%", end="")
        else:
            print(f"\r  Downloading: {count * block_size / 1024 / 1024:.1f} MB", end="")

    try:
        print(f"  Source: {url}")
        urllib.request.urlretrieve(url, zip_path, reporthook=_progress)
        print() # Newline after progress
        
        print("  Extracting ...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # The zip contains a folder like 'ffmpeg-6.0-essentials_build/bin/ffmpeg.exe'
            for member in zip_ref.namelist():
                if member.endswith("ffmpeg.exe"):
                    with zip_ref.open(member) as source, open(ffmpeg_exe, "wb") as target:
                        import shutil
                        shutil.copyfileobj(source, target)
                    break
        
        os.remove(zip_path)
        if os.path.isfile(ffmpeg_exe):
            print("  [SUCCESS] FFmpeg installed locally.")
            return ffmpeg_exe
    except Exception as e:
        print(f"  [ERROR] Failed to download FFmpeg: {e}")
        
    raise FileNotFoundError(
        "ffmpeg not found and auto-download failed. Install it manually and add it to your PATH."
    )


def _test_encoder(ffmpeg_path: str, encoder_name: str) -> bool:
    """Test if an encoder actually works on this hardware."""
    # Note: Some hardware encoders (like NVENC) require a minimum resolution (e.g. 128x128).
    test_cmd = [
        ffmpeg_path, "-y", "-f", "lavfi", "-i", "color=c=black:s=256x256",
        "-frames:v", "1", "-c:v", encoder_name, "-f", "null", "-"
    ]
    try:
        subprocess.run(test_cmd, capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


# ── Quality and Encoder mapping ────────────────────────────────────────────────

QUALITY_MAP = {
    # Intel Quick Sync (Priority)
    "h264_qsv": {
        "low":  ["-global_quality", "26"],
        "mid":  ["-global_quality", "21"],
        "high": ["-global_quality", "16"],
    },
    "hevc_qsv": {
        "low":  ["-global_quality", "28"],
        "mid":  ["-global_quality", "22"],
        "high": ["-global_quality", "17"],
    },
    "vp9_qsv": {
        "low":  ["-global_quality", "32"],
        "mid":  ["-global_quality", "25"],
        "high": ["-global_quality", "19"],
    },
    # NVIDIA NVENC
    "h264_nvenc": {
        "low":  ["-preset", "p4", "-rc", "vbr", "-cq", "26"],
        "mid":  ["-preset", "p4", "-rc", "vbr", "-cq", "21"],
        "high": ["-preset", "p4", "-rc", "vbr", "-cq", "17"],
    },
    "hevc_nvenc": {
        "low":  ["-preset", "p4", "-rc", "vbr", "-cq", "28"],
        "mid":  ["-preset", "p4", "-rc", "vbr", "-cq", "22"],
        "high": ["-preset", "p4", "-rc", "vbr", "-cq", "17"],
    },
    # AMD AMF
    "h264_amf": {
        "low":  ["-quality", "speed", "-rc", "vbr"],
        "mid":  ["-quality", "balanced", "-rc", "vbr"],
        "high": ["-quality", "quality", "-rc", "vbr"],
    },
    "hevc_amf": {
        "low":  ["-quality", "speed", "-rc", "vbr"],
        "mid":  ["-quality", "balanced", "-rc", "vbr"],
        "high": ["-quality", "quality", "-rc", "vbr"],
    },
    # Software fallbacks
    "libx264": {
        "low":  ["-preset", "veryfast", "-crf", "23"],
        "mid":  ["-preset", "veryfast", "-crf", "18"],
        "high": ["-preset", "veryfast", "-crf", "14"],
    },
    "libx265": {
        "low":  ["-preset", "fast", "-crf", "28"],
        "mid":  ["-preset", "fast", "-crf", "22"],
        "high": ["-preset", "fast", "-crf", "17"],
    },
    "libvpx-vp9": {
        "low":  ["-crf", "32", "-b:v", "0"],
        "mid":  ["-crf", "24", "-b:v", "0"],
        "high": ["-crf", "16", "-b:v", "0"],
    }
}


def _pick_encoder(ffmpeg: str, codec: str, cfg: dict) -> tuple[str, list[str]]:
    """
    Returns (encoder_name, args) for the best available encoder.
    codec: "h264", "h265", "vp9"
    """
    quality = cfg.get("quality", "mid")
    hw_pref = cfg.get("hardware_accel", "auto").lower()

    # Define potential hardware encoders by brand
    intel = {"h264": "h264_qsv", "hevc": "hevc_qsv", "h265": "hevc_qsv", "vp9": "vp9_qsv"}
    nvidia = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "h265": "hevc_nvenc"}
    amd = {"h264": "h264_amf", "hevc": "hevc_amf", "h265": "hevc_amf"}
    soft = {"h264": "libx264", "hevc": "libx265", "h265": "libx265", "vp9": "libvpx-vp9"}

    # Build the candidate list based on preference
    candidates = []
    
    if hw_pref == "intel":
        # CPU Hardware (QuickSync)
        candidates = [intel.get(codec)]
    elif hw_pref == "gpu":
        # Dedicated GPU (NVIDIA or AMD)
        candidates = [nvidia.get(codec), amd.get(codec)]
    elif hw_pref == "software":
        # Software (Legacy)
        candidates = [soft.get(codec)]
    else: # auto
        # Global priority: Intel > Dedicated > Software
        candidates = [intel.get(codec), nvidia.get(codec), amd.get(codec), soft.get(codec)]

    # 1. Try preferred candidates first
    candidates = [c for c in candidates if c]
    for enc in candidates:
        if _test_encoder(ffmpeg, enc):
            args = QUALITY_MAP.get(enc, {}).get(quality, [])
            return enc, args

    # 2. Fallback to global priority chain if preferred fails
    # This ensures the tool never fails if a specific choice is unavailable
    global_priority = [intel.get(codec), nvidia.get(codec), amd.get(codec), soft.get(codec)]
    global_priority = [c for c in global_priority if c and c not in candidates]
    
    for enc in global_priority:
        if _test_encoder(ffmpeg, enc):
            args = QUALITY_MAP.get(enc, {}).get(quality, [])
            return enc, args

    raise RuntimeError(f"No suitable encoder found for codec '{codec}'.")


# ── Colour-space conversion ───────────────────────────────────────────────────

# PNG, JPEG, TIFF, BMP, DPX — display-referred, no conversion needed



def _test_filter(ffmpeg_path: str, vf: str, input_fmt: str = None) -> bool:
    """Return True if FFmpeg accepts the given -vf string without error."""
    lavfi_src = "color=c=black:s=128x128"
    if input_fmt:
        lavfi_src += f",format={input_fmt}"
        
    cmd = [
        ffmpeg_path, "-y", "-f", "lavfi", "-i", lavfi_src,
        "-frames:v", "1", "-vf", vf, "-f", "null", "-"
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=5)
        return True
    except Exception:
        return False


def _color_filter(ffmpeg_path: str, ext: str) -> str:
    """
    Return an FFmpeg vf filter fragment for colour-space normalisation.

    EXR  (scene-linear)  → Native RGB sRGB Gamma
    Other formats        → no conversion (already display-referred / sRGB)

    zscale+tonemap and the curves filter are tested at runtime; if either is
    unavailable in the build a simple gamma fallback is used instead.
    """
    e = ext.lower().lstrip(".")

    if e == "exr":
        # Preferred: zscale (libzimg) + tonemap — most accurate pipeline.
        # zscale in  : declare input as scene-linear BT.709
        # tonemap     : Hable/Uncharted 2 — natural highlight roll-off
        # zscale out  : apply Rec.709 gamma 2.4 + limited range flag
        preferred = (
            "zscale=transfer=linear:primaries=bt709:matrix=bt709,"
            "tonemap=hable,"
            "zscale=transfer=bt709:primaries=bt709:matrix=bt709:range=limited"
        )
        if _test_filter(ffmpeg_path, preferred, input_fmt="gbrpf32le"):
            print("[Previewnator] Color: EXR linear -> Hable tone-map -> Rec.709 (zscale)")
            return preferred
        
        # Second choice: Native FFmpeg pure RGB gamma (Replicates mrViewer sRGB view transform exactly)
        # Bypasses the 'eq' filter which forces YUV conversion and lifts the black point, making it look milky.
        # This pipeline converts to 16-bit RGB, preserves absolute deep blacks, and applies pure Rec.709/sRGB math.
        native_tonemap = "format=gbrp16le,lutrgb=r=gammaval(0.454):g=gammaval(0.454):b=gammaval(0.454)"
        if _test_filter(ffmpeg_path, native_tonemap, input_fmt="gbrpf32le"):
            print("[Previewnator] Color: EXR linear -> Rec.709 OETF (Native RGB)")
            return native_tonemap
            
        # Absolute fallback: simpler RGB gamma string.
        fallback = "format=gbrp,lutrgb=r=gammaval(0.454):g=gammaval(0.454):b=gammaval(0.454)"
        print("[Previewnator] Color: EXR linear -> RGB gamma 8-bit fallback")
        return fallback

    # PNG, JPEG, TIFF, BMP, DPX — display-referred, no conversion needed
    return ""


# ── Text overlay helpers ───────────────────────────────────────────────────────

def _find_font() -> str:
    """Return an absolute path to a monospace font for drawtext, escaped for FFmpeg filters."""
    candidates = [
        r"C:\Windows\Fonts\consola.ttf",    # Consolas
        r"C:\Windows\Fonts\cour.ttf",       # Courier New
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for f in candidates:
        if os.path.isfile(f):
            # FFmpeg filter paths on Windows need colons escaped and forward slashes
            # e.g., C:\Path\font.ttf -> C\\:/Path/font.ttf
            return f.replace("\\", "/").replace(":", "\\:")
    return ""


# Fontconfig is no longer used due to instability in static Windows builds.
# We now use absolute font paths in drawtext filters.



def _frames_to_tc(frame: int, fps: float) -> str:
    """Convert absolute frame number to SMPTE-style timecode HH:MM:SS:FF."""
    total_seconds = int(frame / fps)
    ff = int(frame % fps)
    hh = total_seconds // 3600
    mm = (total_seconds % 3600) // 60
    ss = total_seconds % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _build_drawtext_filter(seq: Sequence, cfg: dict, reel_total_frames: int = 0) -> str:
    """Build the FFmpeg drawtext complex filter string for a single shot."""
    fs = cfg["font_size"]
    fc = cfg["font_color"]
    fps = cfg["fps"]

    font_path = _find_font()
    font_arg = f"fontfile='{font_path}':" if font_path else ""

    # Box background for readability
    box_args = "box=1:boxcolor=black@0.55:boxborderw=6:" if cfg["bg_box"] else ""

    # ── Shot name — top-left
    safe_name = seq.name.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    shot_label = (
        f"drawtext={font_arg}{box_args}"
        f"text='{safe_name}':fontcolor={fc}:fontsize={fs}:x=20:y=20"
    )

    # ── Frame / timecode — bottom-left
    offset = seq.first_frame
    tc_text = (
        f"drawtext={font_arg}{box_args}"
        f"text='F\\: %{{eif\\:n+{offset}\\:d}}  |  "
        f"%{{eif\\:(n+{offset})/{int(fps)}\\:d}}s':"
        f"fontcolor={fc}:fontsize={int(fs*0.75)}:x=20:y=h-th-20"
    )

    # ── Duration / total — bottom-right
    reel_info = f" | Total Reel\\: {reel_total_frames}F" if reel_total_frames else ""
    dur_text = (
        f"drawtext={font_arg}{box_args}"
        f"text='F\\: %{{eif\\:n+1\\:d}} / {seq.frame_count}F{reel_info}':"
        f"fontcolor={fc}@0.85:fontsize={int(fs*0.70)}:x=w-tw-20:y=h-th-20"
    )

    return f"{shot_label},{tc_text},{dur_text}"



# ── Scale filter ───────────────────────────────────────────────────────────────

def _scale_filter(max_width: int) -> str:
    """Scale to max_width keeping aspect ratio; ensure even dimensions."""
    return (
        f"scale='if(gt(iw,{max_width}),{max_width},iw)':"
        f"'if(gt(iw,{max_width}),{max_width}*ih/iw,ih)':"
        f"flags=lanczos,"
        f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )


def _build_vf_chain(seq, cfg: dict, ffmpeg: str, reel_total_frames: int = 0) -> str:
    """
    Assemble the complete -vf filter chain in the correct order:
      1. Colour space conversion  (EXR linear / DPX log → Rec.709)
      2. Scale                    (resize to max_width)
      3. Text overlays            (drawtext)
      4. Pixel format             (yuv420p — required by all H.264/H.265 encoders)
    """
    parts = []

    color = _color_filter(ffmpeg, seq.extension)
    if color:
        parts.append(color)

    parts.append(_scale_filter(cfg["max_width"]))
    parts.append(_build_drawtext_filter(seq, cfg, reel_total_frames))
    parts.append("format=yuv420p")

    return ",".join(parts)


# ── Main encode functions ──────────────────────────────────────────────────────

def encode_shot(
    seq: Sequence,
    out_path: str,
    ffmpeg: str,
    encoder: str,
    enc_args: list[str],
    cfg: dict,
    dry_run: bool = False,
    reel_total_frames: int = 0,
) -> None:
    """Encode one image sequence → temp video with overlays."""
    fps = cfg["fps"]
    vf = _build_vf_chain(seq, cfg, ffmpeg, reel_total_frames)

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-framerate", str(fps),
        "-start_number", str(seq.first_frame),
        "-i", seq.pattern,
        "-vf", vf,
        "-c:v", encoder,
        *enc_args,
        "-an", "-y",
        out_path,
    ]

    if dry_run:
        print("  [DRY RUN]", " ".join(f'"{a}"' if " " in a else a for a in cmd))
        return

    # Silence the encoder output to prevent interleaving in parallel mode.
    # We still capture it in case we need to report an error.
    result = subprocess.run(
        cmd, 
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    
    if result.returncode != 0:
        print(f"\n[Previewnator] FFmpeg Error Log:\n{result.stdout}")
        raise RuntimeError(
            f"FFmpeg failed encoding '{seq.name}' (error code {result.returncode})."
        )


def concatenate(clip_paths: list[str], out_path: str, ffmpeg: str,
                dry_run: bool = False) -> None:
    """Concatenate temp clips into the final output using the concat demuxer."""
    list_file = out_path + ".concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in clip_paths:
            # FFmpeg concat demuxer needs forward slashes and escaped apostrophes
            escaped = p.replace("\\", "/").replace("'", "\\'")
            f.write(f"file '{escaped}'\n")

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy", "-y",
        out_path,
    ]

    if dry_run:
        print("  [DRY RUN CONCAT]", " ".join(f'"{a}"' if " " in a else a for a in cmd))
        os.remove(list_file)
        return

    result = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    
    # Robust cleanup: Windows might hold a lock briefly after FFmpeg exits.
    import time
    for _ in range(5):
        try:
            if os.path.exists(list_file):
                os.remove(list_file)
            break
        except PermissionError:
            time.sleep(0.5)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed (error code {result.returncode}).")


def build_reel(
    sequences: list[Sequence],
    cfg: dict,
    output_path: str = "",
    dry_run: bool = False,
    progress_cb=None,
) -> str:
    """
    Full pipeline: encode all shots → concatenate → return final output path.
    Uses multi-threading for the encoding phase.
    """
    ffmpeg = _find_ffmpeg()
    codec = cfg.get("codec", "h264")
    quality = cfg.get("quality", "mid")
    max_workers = cfg.get("max_parallel_tasks", 2)

    encoder_name, encoder_args = _pick_encoder(ffmpeg, codec, cfg)
    
    print(f"[Previewnator] Configuration: {codec} @ {quality} quality")
    print(f"[Previewnator] Parallelism: {max_workers} tasks")
    print(f"[Previewnator] Using encoder: {encoder_name}")

    # Determine output path
    if not output_path:
        base_dir = os.path.dirname(sequences[0].folder)
        if len(sequences) == 1:
            seq = sequences[0]
            name_slug = seq.name.replace(" ", "_").upper()
            ver_match = re.search(r"[\\/](v\d+)[\\/]", seq.folder, re.IGNORECASE)
            if not ver_match:
                ver_match = re.search(r"_(v\d+)", seq.folder, re.IGNORECASE)
            ver_str = f"_{ver_match.group(1).upper()}" if ver_match else ""
            output_path = os.path.join(base_dir, f"{name_slug}{ver_str}_Preview.mp4")
        else:
            first = sequences[0].name.replace(" ", "_").strip().upper()
            last = sequences[-1].name.replace(" ", "_").strip().upper()
            count = len(sequences)
            output_path = os.path.join(base_dir, f"Reel_{count}Shots_{first}_to_{last}.mp4")

    if os.path.exists(output_path):
        base, extension = os.path.splitext(output_path)
        ts = datetime.datetime.now().strftime("_%H%M%S")
        output_path = f"{base}{ts}{extension}"

    tmp_dir = tempfile.mkdtemp(prefix="previewnator_")
    clip_paths = []
    total_frames = sum(s.frame_count for s in sequences)
    
    print(f"[Previewnator] Encoding {len(sequences)} shots ...")

    # Thread-safe progress tracking
    done_count = 0
    progress_lock = threading.Lock()

    def process_shot(idx, seq):
        nonlocal done_count
        tmp_clip = os.path.join(tmp_dir, f"shot_{idx:04d}.mp4")
        
        with progress_lock:
            print(f"  [{idx+1}/{len(sequences)}] Starting: {seq.name}")
            
        encode_shot(seq, tmp_clip, ffmpeg, encoder_name, encoder_args, cfg, dry_run, reel_total_frames=total_frames)
        
        with progress_lock:
            done_count += 1
            print(f"  [{done_count}/{len(sequences)}] Finished: {seq.name}")
            if progress_cb:
                progress_cb(done_count, len(sequences), seq)
        
        return tmp_clip

    try:
        if max_workers > 1 and len(sequences) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Map shots to indices
                futures = {executor.submit(process_shot, i, seq): i for i, seq in enumerate(sequences)}
                
                # Gather results in order of index
                results = {}
                for future in concurrent.futures.as_completed(futures):
                    idx = futures[future]
                    try:
                        results[idx] = future.result()
                    except Exception as e:
                        print(f"\n[Previewnator] Error encoding shot {idx+1}: {e}")
                        raise
                
                # Sort clip paths by original index
                for i in range(len(sequences)):
                    if not dry_run:
                        clip_paths.append(results[i])
        else:
            # Serial fallback
            for i, seq in enumerate(sequences):
                clip_paths.append(process_shot(i, seq))

        if not dry_run:
            print(f"[Previewnator] Concatenating {len(clip_paths)} shots …")
            concatenate(clip_paths, output_path, ffmpeg)
            print(f"[Previewnator] ✓ Done → {output_path}")
        else:
            print(f"[DRY RUN] Output would be: {output_path}")

    finally:
        if not dry_run:
            import time
            time.sleep(0.5)
            for p in clip_paths:
                for _ in range(5):
                    try:
                        if os.path.isfile(p): os.remove(p)
                        break
                    except OSError: time.sleep(0.5)
            for _ in range(5):
                try:
                    if os.path.exists(tmp_dir): shutil.rmtree(tmp_dir, ignore_errors=True)
                    break
                except OSError: time.sleep(0.5)

    return output_path
