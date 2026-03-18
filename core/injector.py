"""
Main injection engine.

Orchestrates the full workflow: extract ISO -> inject kernel -> rebuild ISO.
"""

import shutil
import subprocess
from pathlib import Path

from core.iso import ArchISO, ISOError
from core.kernel import KernelError, download_packages, download_signing_key
from core.surface_devices import (
    LINUX_SURFACE_REPO_NAME,
    LINUX_SURFACE_REPO_URL,
    SurfaceDevice,
)
from utils.log import get_logger

log = get_logger(__name__)


class InjectionError(Exception):
    """Raised when the injection process fails."""


class Injector:
    """
    Orchestrates injecting the linux-surface kernel into an Arch ISO.

    Workflow:
        1. Extract the ISO
        2. Extract the squashfs root filesystem
        3. Download surface kernel packages
        4. Install packages into the root filesystem via chroot + pacman
        5. Configure the linux-surface repository for the installed system
        6. Rebuild the squashfs
        7. Rebuild the ISO
    """

    def __init__(
        self,
        iso_path: str | Path,
        device: SurfaceDevice,
        output_path: str | Path | None = None,
    ):
        self.device = device
        self.iso = ArchISO(iso_path)
        if output_path is None:
            stem = self.iso.iso_path.stem
            output_path = self.iso.iso_path.parent / f"{stem}-surface.iso"
        self.output_path = Path(output_path).resolve()
        self._progress_cb = None

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

        missing = ArchISO.check_dependencies()
        if missing:
            issues.append(
                f"Missing tools: {', '.join(missing)}. "
                f"Install with: sudo pacman -S squashfs-tools libisoburn"
            )

        if shutil.which("curl") is None:
            issues.append("curl is not installed")

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
            issues.append("ISO validation failed - may not be a valid Arch Linux ISO")

        if self.output_path.exists():
            issues.append(f"Output file already exists: {self.output_path}")

        return issues

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

            # Step 2: Find and extract squashfs
            self._progress(20, "Locating root filesystem...")
            squashfs_path = self.iso.find_squashfs()

            self._progress(25, "Extracting root filesystem...")
            self.iso.extract_squashfs(
                squashfs_path, progress_callback=self._progress_cb
            )

            root = self.iso.squashfs_dir

            # Step 3: Download kernel packages
            self._progress(40, "Downloading Surface kernel packages...")
            pkg_cache = self.iso.work_dir / "pkg_cache"
            packages = download_packages(
                self.device, pkg_cache, progress_callback=self._progress_cb
            )

            # Step 4: Download signing key
            self._progress(55, "Setting up linux-surface repository...")
            key_path = download_signing_key(pkg_cache)

            # Step 5: Install into chroot
            self._progress(58, "Installing Surface kernel into root filesystem...")
            self._install_into_root(root, packages, key_path)

            # Step 6: Configure the repo in the installed system
            self._progress(65, "Configuring linux-surface repository...")
            self._configure_repo(root)

            # Step 7: Rebuild squashfs
            self._progress(70, "Rebuilding root filesystem...")
            self.iso.rebuild_squashfs(
                squashfs_path, progress_callback=self._progress_cb
            )

            # Step 8: Update checksums
            self._progress(87, "Updating checksums...")
            self.iso.update_sha512(squashfs_path)

            # Step 9: Rebuild ISO
            self._progress(88, "Rebuilding ISO image...")
            result = self.iso.rebuild_iso(
                self.output_path, progress_callback=self._progress_cb
            )

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
            # Import the signing key
            self._chroot_run(root, [
                "pacman-key", "--init",
            ])
            self._chroot_run(root, [
                "pacman-key", "--populate", "archlinux",
            ])

            # Import surface key
            shutil.copy2(key_path, root / "tmp" / "surface.asc")
            self._chroot_run(root, [
                "pacman-key", "--add", "/tmp/surface.asc",
            ])
            self._chroot_run(root, [
                "pacman-key", "--lsign-key",
                "56C464BAAC421453",
            ])

            # Install the packages
            pkg_paths = [
                f"/var/cache/pacman/pkg/{p.name}" for p in packages
            ]
            self._chroot_run(root, [
                "pacman", "-U", "--noconfirm", *pkg_paths,
            ])

        finally:
            self._unbind_mount(root)

    def _configure_repo(self, root: Path):
        """Add the linux-surface repo to pacman.conf in the root."""
        pacman_conf = root / "etc" / "pacman.conf"
        if not pacman_conf.is_file():
            log.warning("pacman.conf not found in root - skipping repo config")
            return

        content = pacman_conf.read_text()
        repo_block = (
            f"\n[{LINUX_SURFACE_REPO_NAME}]\n"
            f"Server = {LINUX_SURFACE_REPO_URL}\n"
        )

        if LINUX_SURFACE_REPO_NAME not in content:
            content += repo_block
            pacman_conf.write_text(content)
            log.info("Added linux-surface repo to pacman.conf")
        else:
            log.info("linux-surface repo already in pacman.conf")

    def _bind_mount(self, root: Path):
        """Bind mount /dev, /proc, /sys into the chroot."""
        for mount in ["dev", "proc", "sys"]:
            target = root / mount
            target.mkdir(exist_ok=True)
            try:
                subprocess.run(
                    ["mount", "--bind", f"/{mount}", str(target)],
                    capture_output=True, text=True, check=True,
                )
            except subprocess.CalledProcessError:
                log.warning("Could not bind mount /%s (may need root)", mount)

        # Mount /dev/pts
        pts = root / "dev" / "pts"
        pts.mkdir(exist_ok=True)
        try:
            subprocess.run(
                ["mount", "--bind", "/dev/pts", str(pts)],
                capture_output=True, text=True, check=True,
            )
        except subprocess.CalledProcessError:
            pass

        # resolv.conf for network access in chroot
        resolv = root / "etc" / "resolv.conf"
        try:
            shutil.copy2("/etc/resolv.conf", resolv)
        except (OSError, FileNotFoundError):
            pass

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
        full_cmd = ["arch-chroot", str(root)] + cmd
        log.info("chroot: %s", " ".join(cmd))
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0:
                log.warning(
                    "chroot command returned %d: %s",
                    result.returncode, result.stderr,
                )
                # Don't raise for non-critical commands
                if "pacman" in cmd[0] and "-U" in cmd:
                    raise InjectionError(
                        f"Package installation failed: {result.stderr}"
                    )
        except subprocess.TimeoutExpired as exc:
            raise InjectionError(
                f"Chroot command timed out: {' '.join(cmd)}"
            ) from exc
