"""
Previewnator — Image sequence detection and sorting.
Scans a folder, groups files by their naming pattern, and returns Sequence objects.
"""
import os
import re
from dataclasses import dataclass, field
from collections import Counter
from config import SUPPORTED_EXTENSIONS


@dataclass
class Sequence:
    name: str           # human-readable shot label (folder basename)
    folder: str         # absolute folder path
    pattern: str        # FFmpeg-ready glob pattern, e.g. "C:/shots/A/%04d.exr"
    first_frame: int
    last_frame: int
    extension: str
    frame_count: int = field(init=False)

    def __post_init__(self):
        self.frame_count = self.last_frame - self.first_frame + 1

    def duration(self, fps: float) -> float:
        return self.frame_count / fps


# ── Internal helpers ───────────────────────────────────────────────────────────

# Matches trailing frame numbers like: 0001, 00001042, etc.
_FRAME_RE = re.compile(r"^(.*?)(\d+)(\.[^.]+)$")


def _parse_frame_files(folder: str):
    """
    Returns a dict: extension -> list of (frame_number, filename) tuples.
    Only considers files whose extension is in SUPPORTED_EXTENSIONS.
    """
    result: dict[str, list] = {}
    try:
        entries = os.listdir(folder)
    except PermissionError:
        return result

    for fname in entries:
        ext = os.path.splitext(fname)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        m = _FRAME_RE.match(fname)
        if not m:
            continue
        prefix, num_str, suffix_ext = m.group(1), m.group(2), m.group(3)
        frame_num = int(num_str)
        padding = len(num_str)
        key = (prefix, padding, suffix_ext.lower())
        result.setdefault(key, []).append((frame_num, fname))

    return result


def detect(folder: str) -> Sequence | None:
    """
    Detect the primary image sequence in a folder.
    Returns a Sequence, or None if no sequence found.
    """
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return None

    parsed = _parse_frame_files(folder)
    if not parsed:
        return None

    # Pick the group with the most files
    best_key = max(parsed.keys(), key=lambda k: len(parsed[k]))
    prefix, padding, ext = best_key
    frames = sorted(parsed[best_key], key=lambda x: x[0])
    frame_numbers = [f[0] for f in frames]

    if len(frame_numbers) < 2:
        # single-frame "sequences" are not useful for video
        return None

    first = frame_numbers[0]
    last  = frame_numbers[-1]

    # Build FFmpeg input pattern
    pattern = os.path.join(folder, f"{prefix}%0{padding}d{ext}")

    # Shot name logic: Use folder name, but append parent name if folder is generic (like "render")
    base_name = os.path.basename(folder).upper().replace("_", " ").replace("-", " ")
    generic_terms = {"RENDER", "RENDERS", "IMAGES", "IMG", "OUT", "OUTPUT", "EXR", "DPX", "PNG", "V001", "V002"}
    
    if base_name in generic_terms:
        parent_name = os.path.basename(os.path.dirname(folder)).upper().replace("_", " ").replace("-", " ")
        name = f"{parent_name} {base_name}"
    else:
        name = base_name

    return Sequence(
        name=name,
        folder=folder,
        pattern=pattern,
        first_frame=first,
        last_frame=last,
        extension=ext,
    )


def detect_all(folders: list[str]) -> list[Sequence]:
    """
    Detect sequences from a list of folders.
    Recursively scans up to 3 levels deep until sequences are found.
    Returns a sorted list of unique Sequence objects.
    """
    sequences = []
    
    for root in folders:
        root = os.path.abspath(root)
        # Search using a queue (breadth-first) to find closest sequences first
        # queue stores (path, current_depth)
        queue = [(root, 0)]
        found_at_depth = -1
        
        while queue:
            curr_path, depth = queue.pop(0)
            
            # Optimization: If we already found sequences at a shallower depth in this root,
            # we might want to stop, but shots can have multiple parallel sequence folders.
            # We'll allow searching up to depth 3 total.
            if depth > 3:
                continue
                
            seq = detect(curr_path)
            if seq:
                sequences.append(seq)
                # Once we find a sequence in a folder, we don't look into its subfolders
                # (to avoid detecting individual frames as separate things if structured weirdly)
                continue
            
            # If no sequence at this level, check subfolders
            try:
                # Filter out hidden folders and common junk
                entries = sorted([
                    e for e in os.listdir(curr_path)
                    if not e.startswith(".") and os.path.isdir(os.path.join(curr_path, e))
                ])
                for e in entries:
                    queue.append((os.path.join(curr_path, e), depth + 1))
            except PermissionError:
                continue

    # Deduplicate by folder path while preserving order
    seen = set()
    unique = []
    for s in sequences:
        if s.folder not in seen:
            seen.add(s.folder)
            unique.append(s)

    return unique
