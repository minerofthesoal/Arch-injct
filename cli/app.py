"""
CLI interface for Surface Kernel ISO Injector.

Provides an interactive and argument-based command-line interface.
"""

import argparse
import sys
from pathlib import Path

from core.injector import Injector, InjectionError
from core.kernel import KernelError, fetch_latest_kernel_version
from core.surface_devices import (
    get_device,
    get_device_categories,
    list_devices,
)
from utils.log import get_logger, setup_logging

log = get_logger(__name__)

BANNER = r"""
 ____              __                   _  __                    _
/ ___| _   _ _ __ / _| __ _  ___ ___  | |/ /___ _ __ _ __   ___| |
\___ \| | | | '__| |_ / _` |/ __/ _ \ | ' // _ \ '__| '_ \ / _ \ |
 ___) | |_| | |  |  _| (_| | (_|  __/ | . \  __/ |  | | | |  __/ |
|____/ \__,_|_|  |_|  \__,_|\___\___| |_|\_\___|_|  |_| |_|\___|_|
              ___ ____   ___    ___        _           _
             |_ _/ ___| / _ \  |_ _|_ __  (_) ___  ___| |_
              | |\___ \| | | |  | || '_ \ | |/ _ \/ __| __|
              | | ___) | |_| |  | || | | || |  __/ (__| |_
             |___|____/ \___/  |___|_| |_|/ |\___|\___|\__|
                                        |__/
"""

COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
}


def c(text: str, color: str) -> str:
    """Colorize text for terminal output."""
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def print_banner():
    print(c(BANNER, "cyan"))
    print(c("  Surface Kernel ISO Injector (Arch + Mint)", "bold"))
    print(c("  Inject Surface payloads into supported installer ISOs\n", "blue"))


def print_device_table():
    """Print a formatted table of all supported Surface devices."""
    categories = get_device_categories()

    print(c("\n  Supported Surface Devices:", "bold"))
    print(c("  " + "=" * 62, "blue"))

    for cat_name, devices in categories.items():
        print(c(f"\n  {cat_name}:", "magenta"))
        print(c("  " + "-" * 50, "blue"))
        for dev_id, dev in devices:
            notes = f"  ({dev.notes})" if dev.notes else ""
            print(f"    {c(dev_id, 'cyan'):>22s}  {dev.description}{c(notes, 'yellow')}")

    print()


def interactive_select_device() -> str:
    """Interactively prompt the user to pick a Surface device."""
    print_device_table()

    devices = list_devices()
    valid_ids = {d[0] for d in devices}

    while True:
        choice = input(c("  Enter device ID (e.g. sp7, sl4, sg3): ", "green")).strip().lower()
        if choice in valid_ids:
            dev = get_device(choice)
            print(c(f"  Selected: {dev.name}", "bold"))
            if dev.notes:
                print(c(f"  Note: {dev.notes}", "yellow"))
            return choice
        print(c(f"  Invalid device ID: '{choice}'. Try again.", "red"))


def interactive_select_iso() -> str:
    """Interactively prompt for the ISO file path."""
    while True:
        path = input(c("\n  Enter path to ISO (Arch or Mint): ", "green")).strip()
        # Strip surrounding quotes
        path = path.strip("'\"")
        p = Path(path).expanduser().resolve()
        if p.is_file() and p.suffix.lower() == ".iso":
            size_mb = p.stat().st_size / (1024 * 1024)
            print(c(f"  ISO: {p.name} ({size_mb:.1f} MB)", "bold"))
            return str(p)
        if not p.exists():
            print(c(f"  File not found: {p}", "red"))
        elif p.suffix.lower() != ".iso":
            print(c("  File does not have .iso extension", "red"))
        else:
            print(c("  Not a valid file", "red"))


def interactive_select_output(iso_path: str) -> str:
    """Prompt for output path with a sensible default."""
    iso = Path(iso_path)
    default = iso.parent / f"{iso.stem}-surface.iso"

    prompt = f"\n  Output ISO path [{default.name}]: "
    path = input(c(prompt, "green")).strip()

    if not path:
        return str(default)

    path = path.strip("'\"")
    return str(Path(path).expanduser().resolve())


def progress_bar(percent: int, message: str, width: int = 40):
    """Print a progress bar to stderr."""
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    line = f"\r  [{c(bar, 'cyan')}] {percent:3d}% {message}"
    sys.stderr.write(line)
    sys.stderr.flush()
    if percent >= 100:
        sys.stderr.write("\n")


def cmd_inject(args):
    """Handle the 'inject' subcommand."""
    if args.list_devices:
        print_device_table()
        return 0

    # Interactive mode if arguments missing
    if args.device is None:
        device_id = interactive_select_device()
    else:
        device_id = args.device
        if get_device(device_id) is None:
            print(c(f"  Unknown device: {device_id}", "red"))
            print_device_table()
            return 1

    if args.iso is None:
        iso_path = interactive_select_iso()
    else:
        iso_path = args.iso

    if args.output is None:
        if args.device is not None and args.iso is not None:
            # Fully non-interactive - use default output
            output_path = None
        else:
            output_path = interactive_select_output(iso_path)
    else:
        output_path = args.output

    device = get_device(device_id)

    # Confirm
    print(c("\n  === Injection Summary ===", "bold"))
    print(f"  Device:  {c(device.name, 'cyan')}")
    print(f"  ISO:     {c(iso_path, 'cyan')}")
    out_display = output_path or f"{Path(iso_path).stem}-surface.iso"
    print(f"  Output:  {c(out_display, 'cyan')}")

    pkgs = ", ".join([device.kernel_variant] + device.extra_packages)
    print(f"  Packages: {c(pkgs, 'cyan')}")

    if not args.yes:
        confirm = input(c("\n  Proceed? [Y/n] ", "green")).strip().lower()
        if confirm and confirm != "y":
            print(c("  Aborted.", "yellow"))
            return 0

    # Run injection
    injector = Injector(iso_path, device, output_path, distro=args.distro)
    injector.set_progress_callback(progress_bar)

    # Preflight
    issues = injector.preflight_check()
    if issues:
        print(c("\n  Preflight issues found:", "red"))
        for issue in issues:
            print(c(f"    - {issue}", "yellow"))
        if not args.force:
            print(c("  Use --force to proceed anyway.", "yellow"))
            return 1
        print(c("  --force specified, continuing...", "yellow"))

    try:
        result = injector.inject()
        print(c(f"\n  Success! Output ISO: {result}", "green"))
        return 0
    except InjectionError as exc:
        print(c(f"\n  Injection failed: {exc}", "red"))
        return 1


def cmd_info(args):
    """Handle the 'info' subcommand."""
    if args.device:
        dev = get_device(args.device)
        if dev is None:
            print(c(f"Unknown device: {args.device}", "red"))
            return 1

        print(c(f"\n  {dev.name}", "bold"))
        print(f"  Codename:    {dev.codename}")
        print(f"  Description: {dev.description}")
        print(f"  Kernel:      {dev.kernel_variant}")
        print(f"  Packages:    {', '.join(dev.extra_packages)}")
        if dev.notes:
            print(c(f"  Notes:       {dev.notes}", "yellow"))
        return 0

    print_device_table()

    if args.check_version:
        print(c("  Checking latest kernel version...", "blue"))
        try:
            version = fetch_latest_kernel_version()
            print(c(f"  Latest linux-surface kernel: {version}", "green"))
        except KernelError as exc:
            print(c(f"  Could not fetch version: {exc}", "red"))

    return 0


def cmd_check(args):
    """Handle the 'check' subcommand - verify dependencies."""
    from core.iso import ArchISO
    import shutil

    print(c("\n  Dependency Check:", "bold"))
    print(c("  " + "=" * 40, "blue"))

    all_ok = True
    tools = {
        "xorriso": "libisoburn",
        "unsquashfs": "squashfs-tools",
        "mksquashfs": "squashfs-tools",
        "curl": "curl",
        "arch-chroot": "arch-install-scripts",
    }

    for tool, pkg in tools.items():
        found = shutil.which(tool) is not None
        status = c("✓ found", "green") if found else c("✗ missing", "red")
        pkg_hint = f"  (pacman -S {pkg})" if not found else ""
        print(f"    {tool:>15s}  {status}{c(pkg_hint, 'yellow')}")
        if not found:
            all_ok = False

    if all_ok:
        print(c("\n  All dependencies satisfied!", "green"))
    else:
        print(c("\n  Install missing packages before proceeding.", "yellow"))

    return 0 if all_ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surface-iso-injector",
        description="Inject Surface payload into Arch Linux or Linux Mint installer ISOs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s inject                          Interactive mode
  %(prog)s inject -d sp7 -i arch.iso       Non-interactive injection
  %(prog)s inject -d sp7 -i mint.iso --distro mint
  %(prog)s inject -d sp7 -i arch.iso -y    Skip confirmation
  %(prog)s info -d sp7                     Show device info
  %(prog)s info --check-version            Show latest kernel version
  %(prog)s check                           Verify dependencies
  %(prog)s list                            List all devices
        """,
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # inject
    p_inject = subparsers.add_parser(
        "inject", help="Inject Surface kernel into ISO"
    )
    p_inject.add_argument(
        "-d", "--device", type=str, default=None,
        help="Surface device ID (e.g. sp7, sl4). Omit for interactive selection",
    )
    p_inject.add_argument(
        "-i", "--iso", type=str, default=None,
        help="Path to ISO file (Arch or Mint). Omit for interactive selection",
    )
    p_inject.add_argument(
        "--distro", type=str, default="auto",
        choices=["auto", "arch", "mint"],
        help="Distro mode (default: auto-detect from ISO)",
    )
    p_inject.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output ISO path (default: <input>-surface.iso)",
    )
    p_inject.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip confirmation prompt",
    )
    p_inject.add_argument(
        "--force", action="store_true",
        help="Continue even if preflight checks fail",
    )
    p_inject.add_argument(
        "--list-devices", action="store_true",
        help="List supported devices and exit",
    )
    p_inject.set_defaults(func=cmd_inject)

    # info
    p_info = subparsers.add_parser("info", help="Show device/kernel information")
    p_info.add_argument(
        "-d", "--device", type=str, default=None,
        help="Show detailed info for a specific device",
    )
    p_info.add_argument(
        "--check-version", action="store_true",
        help="Check latest linux-surface kernel version",
    )
    p_info.set_defaults(func=cmd_info)

    # check
    p_check = subparsers.add_parser(
        "check", help="Verify system dependencies"
    )
    p_check.set_defaults(func=cmd_check)

    # list (convenience alias)
    p_list = subparsers.add_parser("list", help="List all supported devices")
    p_list.set_defaults(func=lambda args: (print_device_table(), 0)[1])

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        setup_logging(verbose=True)

    print_banner()

    if args.command is None:
        # No subcommand - enter fully interactive mode
        return interactive_mode()

    return args.func(args)


def interactive_mode() -> int:
    """Fully interactive mode when no subcommand is given."""
    print(c("  No command specified - entering interactive mode.\n", "blue"))

    # Step 1: check deps
    print(c("  [1/3] Checking dependencies...", "bold"))
    from core.iso import ArchISO
    missing = ArchISO.check_dependencies()
    if missing:
        print(c(f"  Missing tools: {', '.join(missing)}", "red"))
        print(c("  Install them first: sudo pacman -S squashfs-tools libisoburn", "yellow"))
        return 1
    print(c("  All dependencies OK.\n", "green"))

    # Step 2: select device
    print(c("  [2/3] Select your Surface device:", "bold"))
    device_id = interactive_select_device()

    # Step 3: select ISO
    print(c("\n  [3/3] Select your ISO:", "bold"))
    iso_path = interactive_select_iso()

    output_path = interactive_select_output(iso_path)
    device = get_device(device_id)

    print(c("\n  === Injection Summary ===", "bold"))
    print(f"  Device:  {c(device.name, 'cyan')}")
    print(f"  ISO:     {c(iso_path, 'cyan')}")
    print(f"  Output:  {c(output_path, 'cyan')}")

    confirm = input(c("\n  Proceed? [Y/n] ", "green")).strip().lower()
    if confirm and confirm != "y":
        print(c("  Aborted.", "yellow"))
        return 0

    injector = Injector(iso_path, device, output_path, distro="auto")
    injector.set_progress_callback(progress_bar)

    try:
        result = injector.inject()
        print(c(f"\n  Success! Output ISO: {result}", "green"))
        return 0
    except InjectionError as exc:
        print(c(f"\n  Injection failed: {exc}", "red"))
        return 1
