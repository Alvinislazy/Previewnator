"""
Previewnator — Main CLI entry point.
Usage:
  python previewnator.py <folder1> [folder2 ...] [options]
  python previewnator.py --collect <path>   (called by context menu)
"""
import os
import sys
import argparse
import subprocess
import concurrent.futures
import threading

# Allow running from any directory
sys.path.insert(0, os.path.dirname(__file__))

import config
import sequence as seq_mod
import encoder


def parse_args():
    p = argparse.ArgumentParser(
        prog="previewnator",
        description="Convert image sequence folders into a single VFX reel preview video.",
    )
    p.add_argument("folders", nargs="*", metavar="FOLDER",
                   help="Folders containing image sequences (DPX/EXR/PNG/…)")
    p.add_argument("--fps", type=float, default=None,
                   help="Frame rate (default: 24)")
    p.add_argument("--codec", choices=["h264", "hevc", "h265", "vp9"], default=None,
                   help="Output codec: h264 (default), hevc/h265, or vp9")
    p.add_argument("--batch-indiv", action="store_true",
                   help="Process each input folder as a separate individual preview")
    p.add_argument("--output", "-o", default=None,
                   help="Output file path (default: ReelPreview_<timestamp>.mp4 "
                        "next to the first input folder)")
    p.add_argument("--max-width", type=int, default=None,
                   help="Max output width in pixels (default: 1920)")
    p.add_argument("--no-open", action="store_true",
                   help="Do not open the video when done")
    p.add_argument("--dry-run", action="store_true",
                   help="Print FFmpeg commands without executing them")
    return p.parse_args()


def main():
    args = parse_args()

    folders = args.folders
    if not folders:
        print("Previewnator: no folders specified. Use --help for usage.", file=sys.stderr)
        sys.exit(1)

    # ── Validate all paths ────────────────────────────────────────────────────
    bad = [f for f in folders if not os.path.isdir(f)]
    if bad:
        for b in bad:
            print(f"  [!] Not a directory: {b}", file=sys.stderr)
        sys.exit(1)

    # ── Load config then apply CLI overrides ──────────────────────────────────
    cfg = config.load(install_dir=os.path.dirname(__file__))
    if args.fps        is not None: cfg["fps"]       = args.fps
    if args.codec      is not None: cfg["codec"]     = args.codec.replace("h265", "hevc")
    if args.max_width  is not None: cfg["max_width"] = args.max_width
    if args.no_open:                cfg["open_when_done"] = False

    def process_sequences(seqs, output_name=None):
        print(f"[Previewnator] Scanning {len(seqs)} sequence(s) …")
        
        # Detect sequences
        sequences = seq_mod.detect_all(seqs) if isinstance(seqs[0], str) else seqs

        if not sequences:
            print(f"[Previewnator] No image sequences found.", file=sys.stderr)
            return None

        print(f"[Previewnator] Found {len(sequences)} sequence(s):")
        total_frames = 0
        for s in sequences:
            dur = s.duration(cfg["fps"])
            print(f"  • {s.name:<40} {s.frame_count:>6} frames  ({dur:.2f}s)")
            total_frames += s.frame_count

        total_dur = total_frames / cfg["fps"]
        print(f"[Previewnator] Total reel duration: {total_dur:.1f}s at {cfg['fps']}fps\n")

        # Build the reel
        out_path = encoder.build_reel(
            sequences=sequences,
            cfg=cfg,
            output_path=output_name or "",
            dry_run=args.dry_run,
        )

        # Open the result
        if not args.dry_run and cfg["open_when_done"] and os.path.isfile(out_path):
            try:
                os.startfile(out_path)
            except Exception:
                subprocess.Popen(["start", out_path], shell=True)
        
        return out_path

    if args.batch_indiv:
        # Disable auto-open for individual shots in batch mode
        cfg["open_when_done"] = False
        max_workers = cfg.get("max_parallel_tasks", 2)
        
        print(f"[Previewnator] BATCH INDIVIDUAL MODE: Processing {len(folders)} items (Parallelism: {max_workers}).\n")
        
        # We need to process each folder separately but in parallel
        # Note: build_reel itself is also multi-threaded, but if sequences=1, it uses 1 thread.
        # So parallelizing at the folder level is perfect here.
        final_outputs = []
        lock = threading.Lock()

        def process_folder(folder_path):
            folder_name = os.path.basename(folder_path)
            with lock:
                print(f"  [START] {folder_name}")
            
            try:
                # Force build_reel to use 1 worker internally if we are already parallelizing folders
                # This prevents thread explosion (max_workers * max_workers)
                batch_cfg = dict(cfg)
                batch_cfg["max_parallel_tasks"] = 1
                
                out = process_sequences([folder_path])
                if out:
                    with lock:
                        print(f"  [DONE]  {folder_name}")
                    return out
            except Exception as e:
                with lock:
                    print(f"  [ERROR] {folder_name}: {e}")
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(process_folder, folders))
            final_outputs = [r for r in results if r]
        
        print(f"\n[Previewnator] BATCH SUCCESS: {len(final_outputs)}/{len(folders)} previews generated.")
    else:
        # Standard merge mode
        output_path = process_sequences(folders, output_name=args.output)
        if output_path and not args.dry_run:
            print(f"\n[Previewnator] SUCCESS: Output -> {output_path}")


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:
        if isinstance(e, SystemExit) and e.code == 0:
            sys.exit(0)
            
        # Log error to stderr
        import traceback
        print(f"\n[Previewnator] CRITICAL ERROR: {e}", file=sys.stderr)
        if not isinstance(e, SystemExit):
            traceback.print_exc()
            
        # Keep window open if we have arguments (usually called from context menu)
        # or if we are in a console-like environment.
        if len(sys.argv) > 1:
             print("\n" + "="*60)
             print("An error occurred during processing.")
             input("Press Enter to close this window...")
        sys.exit(1)
