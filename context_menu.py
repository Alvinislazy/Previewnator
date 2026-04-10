"""
Previewnator — Windows context menu installer / uninstaller.
Adds 'Previewnator' cascading menu to the right-click menu for folders.

Run as:
  python context_menu.py --install
  python context_menu.py --uninstall
"""
import os
import sys
import argparse
import winreg
import subprocess
import time
import hashlib
import tempfile
import urllib.request
import zipfile
import shutil
import json
import config

# Registry path for the folder context menu (per-user, no admin required)
# Registry path for the folder context menu (per-user, no admin required)
REG_KEY_DIR   = r"Software\Classes\Directory\shell\Previewnator"
REG_KEY_BACK  = r"Software\Classes\Directory\Background\shell\Previewnator"

# CommandStore: the reliable way to create 3-level-deep flyouts in Explorer
COMMANDSTORE_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Explorer\CommandStore\shell"
COMMAND_PREFIX    = "Previewnator."  # namespace all our commands

MENU_LABEL    = "Previewnator "


# Absolute path to this script's directory
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(SCRIPT_DIR, "previewnator.py")

# Permanent installation directory in AppData
INSTALL_DIR = os.path.expandvars(r"%APPDATA%\Previewnator")

def _relocate_to_appdata():
    """Copy all necessary files to the permanent AppData location."""
    if SCRIPT_DIR.lower() == INSTALL_DIR.lower():
        return False # Already there
        
    print(f"[Previewnator] Relocating to permanent home: {INSTALL_DIR}")
    os.makedirs(INSTALL_DIR, exist_ok=True)
    
    # Files to copy
    files = [f for f in os.listdir(SCRIPT_DIR) if f.endswith(('.py', '.vbs', '.ini', '.bat'))]
    for f in files:
        shutil.copy2(os.path.join(SCRIPT_DIR, f), os.path.join(INSTALL_DIR, f))
        
    # Subdirectories to copy (bin for ffmpeg)
    bin_dir = os.path.join(SCRIPT_DIR, "bin")
    if os.path.isdir(bin_dir):
        target_bin = os.path.join(INSTALL_DIR, "bin")
        if os.path.exists(target_bin):
            shutil.rmtree(target_bin)
        shutil.copytree(bin_dir, target_bin)
        
    return True

def handle_batch(mode: str, path: str):
    """
    Handles the 'debounce' logic for multi-folder selection.
    When multiple folders are selected, Windows launches this script N times.
    The first one creates a queue file and waits; others append their path and exit.
    """
    # Create a unique queue file based on the parent directory
    parent = os.path.dirname(os.path.abspath(path))
    h = hashlib.md5(parent.encode()).hexdigest()[:8]
    q_file = os.path.join(tempfile.gettempdir(), f"previewnator_q_{h}_{mode}.txt")
    l_file = q_file + ".lock"

    # Append this path to the queue with retry logic against Windows file-locks
    for _ in range(20):
        try:
            with open(q_file, "a", encoding="utf-8") as f:
                f.write(path + "\n")
            break
        except Exception:
            time.sleep(0.05)

    # Check for stale lock file
    if os.path.isfile(l_file):
        try:
            mtime = os.path.getmtime(l_file)
            if (time.time() - mtime) > 10:  # 10 seconds timeout for Master election
                try:
                    os.remove(l_file)
                except Exception:
                    pass
        except Exception:
            pass

    # Try to become the 'Master' process using a lock file
    try:
        fd = os.open(l_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return

    paths = []
    try:
        # Wait for "silence" - ensure all concurrent processes have finished writing
        last_size = -1
        for _ in range(15): # Max ~3 seconds wait
            time.sleep(0.2)
            if os.path.isfile(q_file):
                curr_size = os.path.getsize(q_file)
                if curr_size == last_size and curr_size > 0:
                    break
                last_size = curr_size

        if os.path.isfile(q_file):
            for _ in range(20):
                try:
                    with open(q_file, "r", encoding="utf-8") as f:
                        paths = sorted(list(set(line.strip() for line in f if line.strip())))
                    os.remove(q_file)
                    break
                except Exception:
                    time.sleep(0.05)
    finally:
        os.close(fd)
        if os.path.isfile(l_file):
            try: os.remove(l_file)
            except: pass

    if paths:
        print(f"\n[Previewnator] Coordinating batch process for {len(paths)} folders ...")
        
        if mode == "merge":
            # Launch the main tool in a NEW console window so the user sees progress
            cmd = [sys.executable, SCRIPT_PATH] + paths
            # CREATE_NEW_CONSOLE = 0x00000010
            subprocess.Popen(cmd, creationflags=0x00000010)
        elif mode == "indiv":
            # Launch a single console that processes them one by one
            cmd = [sys.executable, SCRIPT_PATH, "--batch-indiv"] + paths
            subprocess.Popen(cmd, creationflags=0x00000010)


def _set_key_value(key, name, value):
    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _set_key_value_dw(key, name, value):
    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def _delete_key_recursive(hkey, root):
    """Recursively delete a registry key."""
    try:
        with winreg.OpenKey(hkey, root, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    name = winreg.EnumKey(k, 0)
                    _delete_key_recursive(hkey, root + "\\" + name)
                except OSError:
                    break
        winreg.DeleteKey(hkey, root)
    except FileNotFoundError:
        pass



def install(refresh_only=False):
    if not refresh_only:
        # 1. Relocate to AppData if currently elsewhere
        if _relocate_to_appdata():
            # Re-launch from the NEW location and then exit
            new_script = os.path.join(INSTALL_DIR, "context_menu.py")
            subprocess.run([sys.executable, new_script, "--install"])
            sys.exit(0)

        # Increase the Windows multiple-selection limit (default is 15)
        try:
            explorer_key = r"Software\Microsoft\Windows\CurrentVersion\Explorer"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, explorer_key, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "MultipleInvokePromptMinimum", 0, winreg.REG_DWORD, 100)
        except Exception:
            pass

        # Explicitly clean target keys before installing
        _delete_key_recursive(winreg.HKEY_CURRENT_USER, REG_KEY_DIR)
        _delete_key_recursive(winreg.HKEY_CURRENT_USER, REG_KEY_BACK)
            
        # Small delay to let Windows Registry "settle"
        import time
        time.sleep(0.25)

    py_exe = sys.executable
    vbs_launcher = os.path.join(SCRIPT_DIR, "silent_run.vbs")
    
    # Ensure the silent launcher VBS exists
    if not os.path.isfile(vbs_launcher):
        with open(vbs_launcher, "w", encoding="utf-8") as f:
            f.write('Set objArgs = WScript.Arguments\n'
                    'If objArgs.Count < 2 Then WScript.Quit\n'
                    'Set objShell = CreateObject("WScript.Shell")\n'
                    'strArgs = ""\n'
                    'For i = 0 to objArgs.Count - 1\n'
                    '    arg = objArgs(i)\n'
                    '    arg = Replace(arg, """", """""")\n'
                    '    strArgs = strArgs & """" & arg & """ "\n'
                    'Next\n'
                    'objShell.Run strArgs, 0, False\n')

    this_script = os.path.abspath(__file__)
    cfg = config.load(install_dir=SCRIPT_DIR)
    
    curr_codec = cfg.get("codec", "h264")
    curr_quality = cfg.get("quality", "mid")
    curr_fps = int(cfg.get("fps", 24))
    curr_accel = cfg.get("hardware_accel", "intel").lower() # Default to intel

    # The magic silent command: wscript //nologo launcher.vbs python.exe script.py --arg ...
    silent_base = f'wscript.exe //nologo "{vbs_launcher}" "{py_exe}" "{this_script}"'
    
    cmd_merge = f'{silent_base} --run-merge "%1"'
    cmd_indiv = f'{silent_base} --run-indiv "%1"'

    # ── Build the menu tree ──────────────────────────────────────────────────
    # Windows Explorer only reliably supports ~3 levels of inline cascading
    # menus under HKCU.  To keep everything visible and working, we put the
    # settings submenus (Hardware, FPS, Quality, Codec) as DIRECT siblings of
    # the action items (Merge / Indiv), so the deepest fly-out is only:
    #   Level 1: "Previewnator"
    #   Level 2: "Quality: Mid"  (flyout arrow)
    #   Level 3: "* Mid", "  Low", "  High"  (leaf items with commands)

    def _add_leaf(parent_key: str, slot: str, label: str, cmd: str):
        """Add a clickable leaf item under a parent shell key."""
        item_key = parent_key + f"\\shell\\{slot}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, item_key) as k:
            _set_key_value(k, "MUIVerb", label)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, item_key + r"\command") as k:
            _set_key_value(k, "", cmd)

    def _add_submenu(parent_key: str, slot: str, label: str):
        """Add a submenu (flyout) using ExtendedSubCommandsKey to bypass item limits."""
        # The Windows Shell limits inline 'shell' cascade menus to 16 items total.
        # To bypass this, we use ExtendedSubCommandsKey which points to a separate class root.
        sub_key = parent_key + f"\\shell\\{slot}"
        class_name = f"Previewnator.{slot}"
        class_path = f"Software\\Classes\\{class_name}"
        
        # 1. Create the reference key in the main menu
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub_key) as k:
            _set_key_value(k, "MUIVerb", label)
            _set_key_value(k, "ExtendedSubCommandsKey", class_name)
            
        # 2. Return the path to the NEW class's shell key so children are added there
        return class_path

    for base_path in [REG_KEY_DIR, REG_KEY_BACK]:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_path) as k_root:
            _set_key_value(k_root, "MUIVerb", MENU_LABEL)
            _set_key_value(k_root, "SubCommands", "")

        # ── Actions (Level 2) ────────────────────────────────────────────
        _add_leaf(base_path, "01_Merge", "Merge Selected", cmd_merge)
        _add_leaf(base_path, "02_Indiv", "Process Individually", cmd_indiv)

        # ── Hardware (Level 2 submenu → Level 3 leaves) ──────────────────
        hw_display = {"intel": "CPU", "gpu": "GPU"}
        h_label = f"Hardware: {hw_display.get(curr_accel, 'Auto')}"
        hw_key = _add_submenu(base_path, "03_Accel", h_label)
        for idx, (id_val, name) in enumerate([
            ("intel",    "CPU (Hardware)"),
            ("gpu",      "GPU (Dedicated)"),
        ]):
            label = f"* {name}" if id_val == curr_accel else f"  {name}"
            cmd   = f'{silent_base} --set-config hardware_accel {id_val}'
            _add_leaf(hw_key, f"{idx:02d}_{id_val}", label, cmd)

        # ── FPS (Level 2 submenu → Level 3 leaves) ───────────────────────
        fps_key = _add_submenu(base_path, "04_FPS", f"FPS: {curr_fps}")
        for idx, f in enumerate([24, 30, 60]):
            label = f"* {f}" if int(f) == curr_fps else f"  {f}"
            cmd   = f'{silent_base} --set-config fps {f}'
            _add_leaf(fps_key, f"{idx:02d}_fps{f}", label, cmd)

        # ── Quality (Level 2 submenu → Level 3 leaves) ───────────────────
        q_key = _add_submenu(base_path, "05_Quality",
                             f"Quality: {curr_quality.capitalize()}")
        for idx, (q, q_name) in enumerate([
            ("low", "Low"), ("mid", "Mid"), ("high", "High"),
        ]):
            label = f"* {q_name}" if q == curr_quality else f"  {q_name}"
            cmd   = f'{silent_base} --set-config quality {q}'
            _add_leaf(q_key, f"{idx:02d}_{q}", label, cmd)

        # ── Codec (Level 2 submenu → Level 3 leaves) ─────────────────────
        c_key = _add_submenu(base_path, "06_Codec",
                             f"Codec: {curr_codec.upper()}")
        for idx, (c, c_name) in enumerate([
            ("h264", "H.264"), ("h265", "H.265"), ("vp9", "VP9"),
        ]):
            label = f"* {c_name}" if c == curr_codec else f"  {c_name}"
            cmd   = f'{silent_base} --set-config codec {c}'
            _add_leaf(c_key, f"{idx:02d}_{c}", label, cmd)

    print(f"[Previewnator] Context menu installed (Codec: {curr_codec}, Quality: {curr_quality}, FPS: {curr_fps}, Accel: {curr_accel})")


def uninstall():
    # 1. Clean up ALL possible class-based flyouts we've ever used
    # This covers the CommandStore/ExtendedSubCommandsKey variants
    prefixes = ["Previewnator.", "ReelForge."]
    suffixes = ["03_Accel", "04_FPS", "05_Quality", "06_Codec", "Codecs", "FPS", "Quality", "Hardware"]
    for p in prefixes:
        for s in suffixes:
            _delete_key_recursive(winreg.HKEY_CURRENT_USER, f"Software\\Classes\\{p}{s}")

    # 2. Clean up ALL possible main menu entries we've ever used
    # This ensures "PreviewnatorUltimate" or "ReelForge" don't become ghosts
    main_variants = ["Previewnator", "PreviewnatorUltimate", "ReelForge"]
    for variant in main_variants:
        for base in [r"Software\Classes\Directory\shell", r"Software\Classes\Directory\Background\shell"]:
            path = f"{base}\\{variant}"
            _delete_key_recursive(winreg.HKEY_CURRENT_USER, path)
            # Also check for space-suffixed variants some versions might have created
            _delete_key_recursive(winreg.HKEY_CURRENT_USER, path + " ")

    print("[Previewnator] Registry deep clean complete. Context menu removed.")
    
    # If we are running from the AppData folder, perform a silent self-destruct
    if SCRIPT_DIR.lower() == INSTALL_DIR.lower():
        print(f"[Previewnator] Cleaning up installation folder (silently): {INSTALL_DIR}")
        
        # Windows locks files while they are running. We create a temporary 
        # VBScript that waits for us to exit and then nukes the folder.
        # VBScripts run via wscript.exe are completely invisible.
        vbs_cleanup = os.path.join(tempfile.gettempdir(), "previewnator_cleanup.vbs")
        with open(vbs_cleanup, "w", encoding="utf-8") as f:
            f.write(f'Set objFSO = CreateObject("Scripting.FileSystemObject")\n'
                    f'WScript.Sleep 3000\n'  # Wait 3s for Python to exit
                    f'On Error Resume Next\n'
                    f'count = 0\n'
                    f'Do While objFSO.FolderExists("{INSTALL_DIR}") And count < 60\n'
                    f'    objFSO.DeleteFolder "{INSTALL_DIR}", True\n'
                    f'    If objFSO.FolderExists("{INSTALL_DIR}") Then\n'
                    f'        WScript.Sleep 1000\n'
                    f'        count = count + 1\n'
                    f'    End If\n'
                    f'Loop\n'
                    f'objFSO.DeleteFile WScript.ScriptFullName\n')
        
        # Launch using wscript.exe //nologo (totally invisible)
        subprocess.Popen(["wscript.exe", "//nologo", vbs_cleanup], 
                         creationflags=0x00000008) # 0x8 is DETACHED_PROCESS
        print("  Installation folder will be removed in the background.")




def main():
    p = argparse.ArgumentParser(description="Previewnator Windows context menu manager")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--install",   action="store_true", help="Add context menu entry")
    g.add_argument("--uninstall", action="store_true", help="Remove context menu entry")
    g.add_argument("--run-merge", type=str, metavar="PATH", help="Internal use: handle a selection to merge")
    g.add_argument("--run-indiv", type=str, metavar="PATH", help="Internal use: handle a selection individually")
    g.add_argument("--set-config", nargs=2, metavar=("KEY", "VAL"), help="Update ini setting and refresh menu")

    args = p.parse_args()
    if args.install:
        install()
    elif args.uninstall:
        uninstall()
    elif args.run_merge:
        handle_batch("merge", args.run_merge)
    elif args.run_indiv:
        handle_batch("indiv", args.run_indiv)
    elif args.set_config:
        key, val = args.set_config
        # Always save configuration to the ACTUAL installation dir
        config.save({key: val}, install_dir=INSTALL_DIR)
        # Atomic refresh only updates the labels, much faster and safer
        install(refresh_only=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"\n[Previewnator Context Menu] CRITICAL ERROR: {e}")
        traceback.print_exc()
        input("\nPress Enter to close...")
        sys.exit(1)
