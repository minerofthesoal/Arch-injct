# Surface Kernel ISO Injector

Inject the [linux-surface](https://github.com/linux-surface/linux-surface) kernel into an Arch Linux installer ISO so you can install Arch on a Microsoft Surface device with full hardware support out of the box.

## What It Does

1. Extracts your Arch Linux ISO
2. Downloads the latest `linux-surface` kernel and related packages from the official linux-surface Arch repository
3. Installs them into the ISO's root filesystem
4. Configures the linux-surface pacman repository for the installed system
5. Rebuilds the ISO — ready to flash and boot

The resulting ISO boots with Surface-specific drivers for touchscreen, pen, cameras, Wi-Fi, keyboard, and other hardware that the stock kernel doesn't support well.

## Supported Devices

| Category | Devices |
|---|---|
| **Surface Pro** | Pro 4, 5 (2017), 6, 7, 7+, 8, 9 (Intel), 10 |
| **Surface Laptop** | 1, 2, 3, 4, 5, Go, Go 2, Studio, Studio 2 |
| **Surface Book** | 1, 2, 3 |
| **Surface Go** | 1, 2, 3 |
| **Surface Studio** | Desktop (community support) |

## Requirements

### System packages

```bash
sudo pacman -S squashfs-tools libisoburn curl arch-install-scripts
```

- `squashfs-tools` — for extracting/rebuilding the root filesystem
- `libisoburn` — provides `xorriso` for ISO manipulation
- `curl` — for downloading kernel packages
- `arch-install-scripts` — provides `arch-chroot`

### Python

- Python 3.10+
- No pip packages required for CLI usage

### For the GUI

Install **one** Qt binding:

```bash
# Option A: PyQt6 (recommended)
sudo pacman -S python-pyqt6
# or: pip install PyQt6

# Option B: PyQt5
sudo pacman -S python-pyqt5
# or: pip install PyQt5

# Option C: qtpy (auto-detects installed backend)
pip install qtpy
```

## Installation

Clone and use directly — no install step needed:

```bash
git clone https://github.com/your-user/Arch-injct.git
cd Arch-injct
```

Or install as a package:

```bash
pip install -e .
```

## Usage

### Interactive Mode (easiest)

```bash
sudo python surface_inject.py
```

Walks you through:
1. Dependency check
2. Device selection (shows all supported Surface models)
3. ISO file selection
4. Confirmation and injection

### CLI with Arguments

```bash
# Inject with specific device and ISO
sudo python surface_inject.py inject -d sp7 -i ~/Downloads/archlinux-2024.01.01-x86_64.iso

# Skip confirmation
sudo python surface_inject.py inject -d sp7 -i arch.iso -y

# Custom output path
sudo python surface_inject.py inject -d sl4 -i arch.iso -o ~/surface-arch.iso

# Force past preflight warnings
sudo python surface_inject.py inject -d sp8 -i arch.iso --force
```

### GUI Mode

```bash
sudo python surface_inject.py --gui
```

Features:
- Device dropdown grouped by category (Pro, Laptop, Book, Go)
- File browser for ISO selection
- Real-time progress bar and log output
- Dependency checker built in
- Kernel version checker
- Dark Catppuccin theme

### Other Commands

```bash
# List all supported devices
python surface_inject.py list

# Show info for a specific device
python surface_inject.py info -d sp7

# Check latest kernel version from the repo
python surface_inject.py info --check-version

# Verify system dependencies
python surface_inject.py check
```

### CLI Reference

```
surface-iso-injector [--verbose] [--gui] <command>

Commands:
  inject    Inject Surface kernel into ISO
  info      Show device/kernel information
  check     Verify system dependencies
  list      List all supported devices

inject options:
  -d, --device DEVICE   Surface device ID (e.g. sp7, sl4, sg3)
  -i, --iso PATH        Path to Arch Linux ISO
  -o, --output PATH     Output ISO path (default: <input>-surface.iso)
  -y, --yes             Skip confirmation prompt
  --force               Continue past preflight warnings
  --list-devices        List devices and exit

info options:
  -d, --device DEVICE   Show info for specific device
  --check-version       Query latest kernel version
```

## Device IDs

Quick reference for the `-d` flag:

| ID | Device |
|---|---|
| `sp4`–`sp10` | Surface Pro 4 through 10 |
| `sp7plus` | Surface Pro 7+ |
| `sp9intel` | Surface Pro 9 (Intel) |
| `sl1`–`sl5` | Surface Laptop 1 through 5 |
| `slgo`, `slgo2` | Surface Laptop Go 1, 2 |
| `slstudio`, `slstudio2` | Surface Laptop Studio 1, 2 |
| `sb1`–`sb3` | Surface Book 1 through 3 |
| `sg`–`sg3` | Surface Go 1 through 3 |
| `ss` | Surface Studio (Desktop) |

## Project Structure

```
Arch-injct/
├── surface_inject.py      # Main entry point
├── core/
│   ├── injector.py        # Orchestrates the full injection workflow
│   ├── iso.py             # ISO extraction, squashfs, and rebuild
│   ├── kernel.py          # Kernel package downloading
│   └── surface_devices.py # Device profiles and repo config
├── cli/
│   └── app.py             # CLI interface with argparse
├── gui/
│   └── main_window.py     # Qt6/Qt5 GUI application
├── utils/
│   └── log.py             # Logging configuration
├── pyproject.toml
├── requirements.txt
└── README.md
```

## How It Works (Technical)

1. **ISO extraction** — `xorriso` extracts the ISO contents to a temp directory
2. **Squashfs extraction** — `unsquashfs` unpacks `airootfs.sfs` (the root filesystem)
3. **Package download** — `curl` pulls `linux-surface`, `linux-surface-headers`, and `iptsd` (for touchscreen devices) from `pkg.surfacelinux.com`
4. **Chroot installation** — `arch-chroot` + `pacman -U` installs the packages into the extracted root
5. **Repository config** — Adds the `[linux-surface]` repo to `pacman.conf` so the installed system can update the kernel
6. **Squashfs rebuild** — `mksquashfs` with zstd compression repacks the modified root
7. **Checksum update** — Updates sha512 checksums for the new squashfs
8. **ISO rebuild** — `xorriso` creates the new hybrid ISO with EFI boot support

## Notes

- **Root required** — ISO manipulation and chroot need root privileges
- **Disk space** — You need roughly 3x the ISO size in free space for the working directory
- **Network** — Required during injection to download kernel packages
- **UEFI only** — Surface devices boot via UEFI; the rebuilt ISO supports both UEFI and legacy BIOS
- **ARM Surface devices** (Surface Pro X, Pro 9 5G) are not supported — they use Qualcomm SoCs which need a different kernel approach

## License

MIT — see [LICENSE](LICENSE).
