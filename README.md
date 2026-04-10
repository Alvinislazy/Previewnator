# Previewnator

Previewnator is a high-performance Windows shell extension and command-line tool designed for VFX artists and studios to automate the generation of annotated preview reels from image sequences.

![Previewnator Demo](https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExcjR2bnQwbGVuMmppc2NxaG82bXJ0bjhzN3E1bTBldWFlMHJ3cWgwbCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/6zbtMwsjnlZkhVMANs/giphy.gif)

## Features

- **Deep Windows Integration**: Full cascading context menu support for folders and multiple file selections.
- **Accurate Color Pipeline**: High-precision 16-bit RGB processing for EXR sequences, replicating the standard scene-linear to sRGB view transform found in professional viewers like mrViewer.
- **Hardware Acceleration**: Automatic detection and utilization of Intel QuickSync (QSV), NVIDIA NVENC, and AMD AMF hardware encoders for blisteringly fast exports.
- **Autonomous Dependency Management**: Zero-config setup. The tool automatically detects, downloads, and manages a local FFmpeg binary if it's not found on the system path.
- **Multi-threaded Batching**: Process dozens of shots simultaneously or sequentially with prioritized resource allocation.
- **Configurable Overlays**: Built-in burnt-in metadata including frame numbers, filenames, and timecodes.

## Requirements

- **Windows 10/11**
- **Python 3.7+**
- **FFMPEG (will auto-install)**

## Installation

1. Clone or download this repository to a stable location on your workstation.
2. Run `install.bat`. 
   - *Note: The installer will automatically relocate the tool to `%APPDATA%\Previewnator` so you can safely delete the original download folder once complete.*
3. Right-click any folder containing image sequences to begin.

## Usage

Right click on a single folder or a group of folders. Click Merge selected or process individually. That's it! , You'll find the output video in the parent folder with "Reel" or "Preview" prefix.

### Context Menu
- **Merge Selected**: Combines multiple selected sequence folders into a single preview reel.
- **Process Individually**: Generates a separate preview file for every selected folder in parallel.
- **Sub-Menus**: Quickly toggle Codecs, Quality presets, and FPS settings directly from the right-click menu.

### Command Line
You can also call the tool directly via CLI:
```bash
python previewnator.py "C:\Path\To\Sequence" --codec h265 --quality high --fps 24
```

## Uninstallation
Run `uninstall.bat` from the installation directory. This will clean up all registry entries and remove the application folder from your system.
