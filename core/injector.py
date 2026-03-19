"""
Main injection engine.

Orchestrates the full workflow: extract ISO -> inject kernel -> rebuild ISO.
"""

import shutil
import subprocess
import time
from pathlib import Path

from core.distro_handlers import ArchHandler, DistroHandler, MintHandler
from core.iso import ArchISO, ISOError
from core.kernel import KernelError
from core.network import (
    DNS_ERROR,
    MIRROR_ERROR,
    NETWORK_ERROR,
    apply_fallback_mirrorlist,
    classify_pacman_error,
    ensure_resolv_conf,
    host_network_status,
)
from core.surface_devices import SurfaceDevice
from utils.log import get_logger

log = get_logger(__name__)


class InjectionError(Exception):
    """Raised when the injection process fails."""


class Injector:
    """
    Orchestrates distro-aware ISO payload injection.

    Workflow:
        1. Extract the ISO
        2. Extract the squashfs root filesystem
        3. Run distro-specific payload injection
        4. Rebuild the squashfs
        5. Rebuild the ISO
    """

    def __init__(
        self,
        iso_path: str | Path,
        device: SurfaceDevice,
        output_path: str | Path | None = None,
        distro: str = "auto",
    ):
        self.device = device
        self.iso = ArchISO(iso_path)
        self.distro = distro.lower()
        if self.distro not in {"auto", "arch", "mint"}:
            raise InjectionError(
                f"Unsupported distro option: {distro}. Use arch|mint|auto."
            )
        if output_path is None:
            stem = self.iso.iso_path.stem
            output_path = self.iso.iso_path.parent / f"{stem}-surface.iso"
        self.output_path = Path(output_path).resolve()
        self._progress_cb = None
        self._handler: DistroHandler | None = None

    def set_progress_callback(self, callback):
        """Set a callback: callback(percent: int, message: str)."""
        self._progress_cb = callback

    def _progress(self, pct: int, msg: str):
        log.info("[%3d%%] %s", pct, msg)
        if self._progress_cb:
            self._progress_cb(pct, msg)

    def preflight_check(self) -> list[str]:
        """Run checks before starting. Returns list of issues (empty = OK)."""
        issues = []
        import os

        missing = ArchISO.check_dependencies()
        if missing:
            issues.append(
                f"Missing tools: {', '.join(missing)}. "
                "Install with pacman: sudo pacman -S squashfs-tools libisoburn "
                "or apt: sudo apt install squashfs-tools xorriso"
            )

        # Check disk space
        needed = self.iso.estimate_space_needed_mb()
        try:
            import os
            stat = os.statvfs(str(self.iso.iso_path.parent))
            free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
            if free_mb < needed:
                issues.append(
                    f"Insufficient disk space: ~{needed:.0f} MB needed, "
                    f"{free_mb:.0f} MB available"
                )
        except OSError:
            pass

        if not self.iso.validate_iso():
            issues.append("ISO validation failed - may not be a readable ISO image")

        detected = self.iso.detect_distro()
        if self.distro == "auto" and detected == "unknown":
            issues.append(
                "Could not detect supported distro from ISO (supported: arch, mint)"
            )
        elif self.distro != "auto" and detected != "unknown" and detected != self.distro:
            issues.append(
                f"Distro mismatch: requested '{self.distro}' but ISO looks like '{detected}'"
            )
        arch_flow = (self.distro == "arch") or (self.distro == "auto" and detected == "arch")
        if arch_flow and os.geteuid() != 0:
            issues.append(
                "Arch kernel injection requires root privileges for bind-mount/chroot. "
                "Run with sudo."
            )
        if arch_flow:
            net = host_network_status()
            log.info(
                "network_check stage=preflight internet=%s dns=%s",
                net["internet"], net["dns"],
            )
            if not net["internet"]:
                issues.append("No internet connectivity detected on host.")
            if not net["dns"]:
                issues.append("DNS lookup failed on host (archlinux.org).")

        if self.output_path.exists():
            issues.append(f"Output file already exists: {self.output_path}")

        return issues

    def _resolve_handler(self) -> DistroHandler:
        detected = self.iso.detect_distro()
        chosen = detected if self.distro == "auto" else self.distro
        if chosen not in {"arch", "mint"}:
            raise InjectionError(
                "Unsupported ISO type. Supported distros: Arch Linux, Linux Mint "
                "(and Ubuntu-based casper layouts)."
            )
        if chosen == "arch":
            return ArchHandler(self)
        return MintHandler(self)

    def inject(self) -> Path:
        """
        Run the full injection process.
        Returns path to the output ISO.
        """
        self._progress(0, "Starting Surface kernel injection...")
        self._progress(
            1,
            f"Device: {self.device.name} | ISO: {self.iso.iso_path.name}"
        )

        try:
            # Step 1: Extract ISO
            self._progress(5, "Extracting ISO...")
            self.iso.extract(progress_callback=self._progress_cb)
            self._handler = self._resolve_handler()
            self._progress(10, f"Detected distro: {self._handler.name}")

            # Distro-specific required tools
            for tool in self._handler.required_tools:
                if shutil.which(tool) is None:
                    raise InjectionError(f"Missing required tool for {self._handler.name}: {tool}")

            # Step 2: Find and extract squashfs
            self._progress(20, "Locating root filesystem...")
            squashfs_path, root = self._handler.extract_files()

            # Step 3+: Distro-specific payload
            self._handler.inject_payload(root)

            # Step 7: Rebuild squashfs
            self._progress(70, "Rebuilding root filesystem...")
            self._progress(88, "Rebuilding ISO image...")
            result = self._handler.rebuild_iso(squashfs_path)

            self._progress(100, f"Done! Output: {result}")
            return result

        except (ISOError, KernelError) as exc:
            raise InjectionError(str(exc)) from exc
        finally:
            self.iso.cleanup()

    def _install_into_root(
        self, root: Path, packages: list[Path], key_path: Path
    ):
        """Install downloaded packages into the extracted root filesystem."""
        # Copy packages into the chroot
        chroot_cache = root / "var" / "cache" / "pacman" / "pkg"
        chroot_cache.mkdir(parents=True, exist_ok=True)

        for pkg in packages:
            shutil.copy2(pkg, chroot_cache / pkg.name)

        # Copy the GPG key
        chroot_gnupg = root / "etc" / "pacman.d" / "gnupg"
        chroot_gnupg.mkdir(parents=True, exist_ok=True)

        # Mount necessary filesystems for chroot
        self._bind_mount(root)

        try:
            self._prepare_arch_pacman(root, key_path)

            # Install the packages
            pkg_paths = [
                f"/var/cache/pacman/pkg/{p.name}" for p in packages
            ]
            self._chroot_run(root, [
                "pacman", "-U", "--noconfirm", *pkg_paths,
            ])

        finally:
            self._unbind_mount(root)

    def _install_into_root_from_repo(
        self, root: Path, package_names: list[str], key_path: Path
    ):
        """
        Install packages directly from configured repositories inside the chroot.
        Used as fallback when direct package-file lookup/download fails.
        """
        self._bind_mount(root)
        try:
            self._prepare_arch_pacman(root, key_path)
            self._chroot_run(root, [
                "pacman", "-Sy", "--noconfirm", *package_names,
            ])
        finally:
            self._unbind_mount(root)

    def _prepare_arch_pacman(self, root: Path, key_path: Path):
        """Initialize pacman keyring in the chroot and trust linux-surface key."""
        self._repair_network(root, reason="pre_pacman_init")
        self._chroot_run(root, [
            "pacman-key", "--init",
        ])
        self._chroot_run(root, [
            "pacman-key", "--populate", "archlinux",
        ])

        shutil.copy2(key_path, root / "tmp" / "surface.asc")
        self._chroot_run(root, [
            "pacman-key", "--add", "/tmp/surface.asc",
        ])
        self._chroot_run(root, [
            "pacman-key", "--lsign-key",
            "56C464BAAC421453",
        ])

    def _bind_mount(self, root: Path):
        """Bind mount /dev, /proc, /sys into the chroot."""
        for mount in ["dev", "proc", "sys"]:
            target = root / mount
            try:
                target.mkdir(parents=True, exist_ok=True)
            except PermissionError:
                log.warning(
                    "Could not prepare mount target %s (permission denied)",
                    target,
                )
                continue
            try:
                subprocess.run(
                    ["mount", "--bind", f"/{mount}", str(target)],
                    capture_output=True, text=True, check=True,
                )
            except subprocess.CalledProcessError:
                log.warning("Could not bind mount /%s (may need root)", mount)

        # Mount /dev/pts
        pts = root / "dev" / "pts"
        try:
            pts.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            log.warning(
                "Could not prepare mount target %s (permission denied)",
                pts,
            )
            return
        try:
            subprocess.run(
                ["mount", "--bind", "/dev/pts", str(pts)],
                capture_output=True, text=True, check=True,
            )
        except subprocess.CalledProcessError:
            pass

        # resolv.conf for network access in chroot
        ensure_resolv_conf(root)

    def _unbind_mount(self, root: Path):
        """Unmount bind mounts from the chroot."""
        for mount in ["dev/pts", "dev", "proc", "sys"]:
            target = root / mount
            try:
                subprocess.run(
                    ["umount", "-l", str(target)],
                    capture_output=True, text=True,
                )
            except subprocess.CalledProcessError:
                pass

    def _chroot_run(self, root: Path, cmd: list[str]):
        """Run a command inside the chroot."""
        if shutil.which("arch-chroot"):
            full_cmd = ["arch-chroot", str(root)] + cmd
        elif shutil.which("chroot"):
            full_cmd = ["chroot", str(root)] + cmd
        else:
            raise InjectionError(
                "No chroot runner found (need arch-chroot or chroot)"
            )
        log.info("chroot: %s", " ".join(cmd))
        max_attempts = 4 if ("pacman" in cmd[0]) else 1

        for attempt in range(1, max_attempts + 1):
            try:
                result = subprocess.run(
                    full_cmd,
                    capture_output=True, text=True, timeout=600,
                )
            except subprocess.TimeoutExpired as exc:
                if attempt >= max_attempts:
                    raise InjectionError(
                        f"Package installation failed ({NETWORK_ERROR}): command timed out in chroot."
                    ) from exc
                self._repair_network(root, reason="timeout")
                wait = 2 ** (attempt - 1)
                log.warning("retry event=timeout attempt=%d wait=%ds", attempt, wait)
                time.sleep(wait)
                continue

            if result.returncode == 0:
                return

            out = f"{result.stdout}\n{result.stderr}"
            kind = classify_pacman_error(out) if "pacman" in cmd[0] else None
            log.warning(
                "chroot_fail cmd=%s code=%d class=%s attempt=%d/%d",
                " ".join(cmd), result.returncode, kind or "UNKNOWN", attempt, max_attempts,
            )

            if "pacman" in cmd[0] and ("-U" in cmd or "-Sy" in cmd):
                if kind and attempt < max_attempts:
                    self._repair_network(root, reason=kind)
                    wait = 2 ** (attempt - 1)
                    log.warning("retry event=pacman attempt=%d class=%s wait=%ds", attempt, kind, wait)
                    time.sleep(wait)
                    continue

                if kind in {NETWORK_ERROR, DNS_ERROR, MIRROR_ERROR}:
                    raise InjectionError(
                        "Package installation failed "
                        f"({kind}). Network unavailable inside build environment. "
                        "Check DNS or container networking."
                    )
                raise InjectionError(f"Package installation failed: {result.stderr}")

            return

    def _repair_network(self, root: Path, reason: str):
        """
        Attempt to make chroot networking usable for pacman operations.
        """
        log.info("netfix event=start reason=%s", reason)
        ensure_resolv_conf(root)
        if reason == MIRROR_ERROR:
            apply_fallback_mirrorlist(root)
        # Try restarting resolver services on host if available.
        for svc in ["systemd-resolved", "NetworkManager"]:
            try:
                subprocess.run(
                    ["systemctl", "restart", svc],
                    capture_output=True, text=True, timeout=15,
                )
                log.info("netfix event=service_restart service=%s", svc)
                break
            except Exception:
                continue
