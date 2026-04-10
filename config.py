"""
Previewnator — Configuration defaults and INI file loading.
"""
import os
import configparser

# ── Default settings ──────────────────────────────────────────────────────────
DEFAULTS = {
    "fps": 24,
    "codec": "h264",          # "h264", "h265", or "vp9"
    "quality": "mid",         # "low", "mid", "high"
    "max_parallel_tasks": 2,  # number of parallel FFmpeg encodes
    "hardware_accel": "intel", # "intel", "gpu", "software"
    "max_width": 1920,
    "font_size": 28,
    "font_color": "white",
    "shadow_color": "black@0.6",
    "bg_box": True,           # draw a dark background box behind text
    "open_when_done": True,   # open the output video in the default player
    "output_dir": "",         # empty = same parent as the first input folder
    "no_audio": True,         # image sequences have no audio
}

SUPPORTED_EXTENSIONS = {".dpx", ".exr", ".png", ".tif", ".tiff",
                        ".jpg", ".jpeg", ".bmp"}

def load(install_dir: str = None) -> dict:
    """Return a settings dict, optionally merging an ini file from install_dir."""
    cfg = dict(DEFAULTS)
    ini_paths = []
    if install_dir:
        ini_paths.append(os.path.join(install_dir, "previewnator.ini"))
    # also check next to this script
    ini_paths.append(os.path.join(os.path.dirname(__file__), "previewnator.ini"))

    for ini_path in ini_paths:
        if os.path.isfile(ini_path):
            parser = configparser.ConfigParser()
            parser.read(ini_path)
            s = parser["previewnator"] if "previewnator" in parser else {}
            if "fps" in s:         cfg["fps"]         = int(s["fps"])
            if "codec" in s:       cfg["codec"]       = s["codec"]
            if "quality" in s:     cfg["quality"]     = s["quality"]
            if "max_parallel_tasks" in s:
                cfg["max_parallel_tasks"] = int(s["max_parallel_tasks"])
            if "hardware_accel" in s: cfg["hardware_accel"] = s["hardware_accel"]
            if "max_width" in s:   cfg["max_width"]   = int(s["max_width"])
            if "font_size" in s:   cfg["font_size"]   = int(s["font_size"])
            if "output_dir" in s:  cfg["output_dir"]  = s["output_dir"]
            if "open_when_done" in s:
                cfg["open_when_done"] = s.getboolean("open_when_done")
            if "bg_box" in s:
                cfg["bg_box"] = s.getboolean("bg_box")
            break  # use only the first found ini

    return cfg

def save(cfg_overrides: dict, install_dir: str = None):
    """Save setting overrides to the ini file."""
    # Resolve the ini path
    if install_dir:
        path = os.path.join(install_dir, "previewnator.ini")
    else:
        path = os.path.join(os.path.dirname(__file__), "previewnator.ini")

    parser = configparser.ConfigParser()
    if os.path.isfile(path):
        parser.read(path)
    
    if "previewnator" not in parser:
        parser["previewnator"] = {}
    
    for k, v in cfg_overrides.items():
        parser["previewnator"][k] = str(v)
    
    # Preserve existing settings but update with overrides
    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)
