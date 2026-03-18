"""
ISO manipulation module.

Handles extracting, modifying, and rebuilding Arch Linux ISO images.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from utils.log import get_logger

log = get_logger(__name__)


class ISOError(Exception):
    """Raised when ISO operations fail."""


class ArchISO:
    """Manages extraction, modification, and rebuild of an Arch Linux ISO."""

    REQUIRED_TOOLS = ["xorriso", "unsquashfs", "mksquashfs"]

    def __init__(self, iso_path: str | Path):
        self.iso_path = Path(iso_path).resolve()
        self._work_dir: Path | None = None
        self._extract_dir: Path | None = None
        self._squashfs_dir: Path | None = None

        if not self.iso_path.is_file():
            raise ISOError(f"ISO file not found: {self.iso_path}")
        if not self.iso_path.suffix.lower() == ".iso":
            raise ISOError(f"Not an ISO file: {self.iso_path}")

    @staticmethod
    def check_dependencies() -> list[str]:
        """Return list of missing required tools."""
        missing = []
        for tool in ArchISO.REQUIRED_TOOLS:
            if shutil.which(tool) is None:
                missing.append(tool)
        return missing

    @property
    def work_dir(self) -> Path:
        if self._work_dir is None:
            self._work_dir = Path(
                tempfile.mkdtemp(prefix="surface-iso-")
            )
            log.info("Work directory: %s", self._work_dir)
        return self._work_dir

    @property
    def extract_dir(self) -> Path:
        if self._extract_dir is None:
            self._extract_dir = self.work_dir / "iso_extract"
            self._extract_dir.mkdir(exist_ok=True)
        return self._extract_dir

    @property
    def squashfs_dir(self) -> Path:
        if self._squashfs_dir is None:
            self._squashfs_dir = self.work_dir / "squashfs_root"
            self._squashfs_dir.mkdir(exist_ok=True)
        return self._squashfs_dir

    def validate_iso(self) -> bool:
        """Basic validation that this looks like an Arch Linux ISO."""
        try:
            result = subprocess.run(
                ["xorriso", "-indev", str(self.iso_path), "-ls", "/"],
                capture_output=True, text=True, timeout=30
            )
            output = result.stdout + result.stderr
            return result.returncode == 0 and (
                "arch" in output.lower() or len(output.strip()) > 0
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def extract(self, progress_callback=None) -> Path:
        """Extract the ISO contents."""
        log.info("Extracting ISO: %s", self.iso_path)
        if progress_callback:
            progress_callback(5, "Extracting ISO contents...")

        try:
            subprocess.run(
                [
                    "xorriso", "-osirrox", "on",
                    "-indev", str(self.iso_path),
                    "-extract", "/", str(self.extract_dir),
                ],
                capture_output=True, text=True, check=True, timeout=300,
            )
        except subprocess.CalledProcessError as exc:
            raise ISOError(f"ISO extraction failed: {exc.stderr}") from exc

        if progress_callback:
            progress_callback(20, "ISO extracted")
        log.info("ISO extracted to %s", self.extract_dir)
        return self.extract_dir

    def find_squashfs(self) -> Path:
        """Locate the airootfs squashfs image inside the extracted ISO."""
        candidates = [
            self.extract_dir / "arch" / "x86_64" / "airootfs.sfs",
            self.extract_dir / "arch" / "x86_64" / "airootfs.erofs",
        ]
        # Also search recursively
        for sfs in self.extract_dir.rglob("airootfs.sfs"):
            candidates.insert(0, sfs)
        for erofs in self.extract_dir.rglob("airootfs.erofs"):
            candidates.insert(0, erofs)

        for candidate in candidates:
            if candidate.is_file():
                log.info("Found squashfs: %s", candidate)
                return candidate

        raise ISOError(
            "Could not find airootfs.sfs or airootfs.erofs in extracted ISO. "
            "Is this a valid Arch Linux ISO?"
        )

    def extract_squashfs(self, squashfs_path: Path, progress_callback=None) -> Path:
        """Extract the squashfs filesystem."""
        log.info("Extracting squashfs: %s", squashfs_path)
        if progress_callback:
            progress_callback(25, "Extracting root filesystem...")

        try:
            subprocess.run(
                ["unsquashfs", "-d", str(self.squashfs_dir), "-f", str(squashfs_path)],
                capture_output=True, text=True, check=True, timeout=600,
            )
        except subprocess.CalledProcessError as exc:
            raise ISOError(f"Squashfs extraction failed: {exc.stderr}") from exc

        if progress_callback:
            progress_callback(40, "Root filesystem extracted")
        log.info("Squashfs extracted to %s", self.squashfs_dir)
        return self.squashfs_dir

    def rebuild_squashfs(self, squashfs_path: Path, progress_callback=None):
        """Rebuild the squashfs image from modified root."""
        log.info("Rebuilding squashfs...")
        if progress_callback:
            progress_callback(70, "Rebuilding root filesystem (this takes a while)...")

        # Remove old squashfs
        squashfs_path.unlink(missing_ok=True)

        try:
            subprocess.run(
                [
                    "mksquashfs", str(self.squashfs_dir), str(squashfs_path),
                    "-comp", "zstd", "-Xcompression-level", "15",
                    "-b", "1M",
                ],
                capture_output=True, text=True, check=True, timeout=1800,
            )
        except subprocess.CalledProcessError as exc:
            raise ISOError(f"Squashfs rebuild failed: {exc.stderr}") from exc

        if progress_callback:
            progress_callback(85, "Root filesystem rebuilt")
        log.info("Squashfs rebuilt: %s", squashfs_path)

    def update_sha512(self, squashfs_path: Path):
        """Update the sha512 checksum file for the squashfs image."""
        sha_file = squashfs_path.parent / (squashfs_path.name + ".sha512")
        if not sha_file.exists():
            # Try alternate naming
            for candidate in squashfs_path.parent.glob("*.sha512"):
                sha_file = candidate
                break

        sha = hashlib.sha512()
        with open(squashfs_path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                sha.update(chunk)

        checksum_line = f"{sha.hexdigest()}  {squashfs_path.name}\n"
        target = squashfs_path.parent / (squashfs_path.name + ".sha512")
        target.write_text(checksum_line)
        log.info("Updated checksum: %s", target)

    def rebuild_iso(self, output_path: str | Path, progress_callback=None) -> Path:
        """Rebuild the ISO image from modified contents."""
        output_path = Path(output_path).resolve()
        log.info("Rebuilding ISO -> %s", output_path)
        if progress_callback:
            progress_callback(88, "Rebuilding ISO image...")

        # Find the EFI boot image
        efi_boot = None
        for candidate in [
            self.extract_dir / "EFI" / "archiso" / "efiboot.img",
            self.extract_dir / "boot" / "grub" / "efi.img",
        ]:
            if candidate.is_file():
                efi_boot = candidate
                break
        if efi_boot is None:
            for img in self.extract_dir.rglob("efiboot.img"):
                efi_boot = img
                break

        efi_rel = str(efi_boot.relative_to(self.extract_dir)) if efi_boot else None

        cmd = [
            "xorriso",
            "-as", "mkisofs",
            "-iso-level", "3",
            "-full-iso9660-filenames",
            "-volid", "ARCH_SURFACE",
            "-eltorito-boot", "boot/syslinux/isolinux.bin",
            "-eltorito-catalog", "boot/syslinux/boot.cat",
            "-no-emul-boot",
            "-boot-load-size", "4",
            "-boot-info-table",
        ]

        if efi_rel:
            cmd += [
                "-eltorito-alt-boot",
                "-e", efi_rel,
                "-no-emul-boot",
                "-isohybrid-gpt-basdat",
            ]

        # Check for isolinux.bin / syslinux - adjust if hybrid MBR needed
        isolinux = self.extract_dir / "boot" / "syslinux" / "isolinux.bin"
        if isolinux.is_file():
            cmd += ["-isohybrid-mbr", str(isolinux)]

        cmd += ["-output", str(output_path), str(self.extract_dir)]

        try:
            subprocess.run(
                cmd, capture_output=True, text=True, check=True, timeout=1800,
            )
        except subprocess.CalledProcessError as exc:
            raise ISOError(f"ISO rebuild failed: {exc.stderr}") from exc

        if progress_callback:
            progress_callback(98, "ISO rebuilt successfully")
        log.info("ISO rebuilt: %s", output_path)
        return output_path

    def cleanup(self):
        """Remove all temporary working files."""
        if self._work_dir and self._work_dir.exists():
            log.info("Cleaning up: %s", self._work_dir)
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = None
            self._extract_dir = None
            self._squashfs_dir = None

    def get_iso_size_mb(self) -> float:
        return self.iso_path.stat().st_size / (1024 * 1024)

    def estimate_space_needed_mb(self) -> float:
        """Rough estimate: 3x the ISO size for working space."""
        return self.get_iso_size_mb() * 3

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()
