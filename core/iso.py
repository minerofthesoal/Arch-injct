"""
ISO manipulation module.

Handles extracting, modifying, and rebuilding Arch Linux ISO images.
"""

import hashlib
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
        """Basic validation that this is a readable ISO image."""
        try:
            result = subprocess.run(
                ["xorriso", "-indev", str(self.iso_path), "-ls", "/"],
                capture_output=True, text=True, timeout=30
            )
            output = result.stdout + result.stderr
            return result.returncode == 0 and len(output.strip()) > 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def detect_distro(self) -> str:
        """
        Detect distro family from ISO label and filesystem layout.
        Returns: "arch", "mint", or "unknown".
        """
        label = self.get_iso_label().lower()

        if any(x in label for x in ["arch", "archlinux"]):
            return "arch"
        if any(x in label for x in ["mint", "linuxmint", "ubuntu"]):
            return "mint"

        root_listing = self._iso_ls("/")
        if "casper" in root_listing:
            return "mint"
        if "arch" in root_listing:
            return "arch"
        return "unknown"

    def get_iso_label(self) -> str:
        """Read ISO volume label via xorriso."""
        try:
            result = subprocess.run(
                ["xorriso", "-indev", str(self.iso_path), "-pvd_info"],
                capture_output=True, text=True, timeout=30, check=True,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return ""

        for line in (result.stdout + "\n" + result.stderr).splitlines():
            if "Volume id" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip("'\"")
        return ""

    def _iso_ls(self, iso_path: str) -> str:
        """List path directly from ISO without full extraction."""
        try:
            result = subprocess.run(
                ["xorriso", "-indev", str(self.iso_path), "-ls", iso_path],
                capture_output=True, text=True, timeout=30,
            )
            return (result.stdout + "\n" + result.stderr).lower()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

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

    def find_squashfs(self, distro: str = "arch") -> Path:
        """Locate the distro rootfs image inside the extracted ISO."""
        candidates = [
            self.extract_dir / "arch" / "x86_64" / "airootfs.sfs",
            self.extract_dir / "arch" / "x86_64" / "airootfs.erofs",
            self.extract_dir / "casper" / "filesystem.squashfs",
        ]
        if distro == "mint":
            candidates = [
                self.extract_dir / "casper" / "filesystem.squashfs",
                self.extract_dir / "casper" / "filesystem.sfs",
            ] + candidates

        # Also search recursively
        for sfs in self.extract_dir.rglob("airootfs.sfs"):
            candidates.insert(0, sfs)
        for erofs in self.extract_dir.rglob("airootfs.erofs"):
            candidates.insert(0, erofs)
        for mint_fs in self.extract_dir.rglob("filesystem.squashfs"):
            candidates.insert(0, mint_fs)
        for mint_sfs in self.extract_dir.rglob("filesystem.sfs"):
            candidates.insert(0, mint_sfs)

        for candidate in candidates:
            if candidate.is_file():
                log.info("Found squashfs: %s", candidate)
                return candidate

        raise ISOError(
            "Could not find supported rootfs image "
            "(airootfs.sfs/airootfs.erofs/filesystem.squashfs). "
            "Is this a supported Arch or Mint ISO?"
        )

    def extract_squashfs(self, squashfs_path: Path, progress_callback=None) -> Path:
        """Extract the squashfs filesystem."""
        log.info("Extracting squashfs: %s", squashfs_path)
        if progress_callback:
            progress_callback(25, "Extracting root filesystem...")

        cmd = ["unsquashfs", "-d", str(self.squashfs_dir), "-f", str(squashfs_path)]
        try:
            subprocess.run(
                cmd,
                capture_output=True, text=True, check=True, timeout=600,
            )
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or "") + (exc.stdout or "")
            xattr_error = (
                "could not write xattr" in err.lower()
                or "security.capability" in err.lower()
            )
            if not xattr_error:
                raise ISOError(f"Squashfs extraction failed: {exc.stderr}") from exc

            # Non-root users can fail on security.capability xattrs.
            # Retry without xattrs so CLI usage works without sudo.
            log.warning(
                "unsquashfs failed while restoring xattrs; retrying with -no-xattrs"
            )
            try:
                subprocess.run(
                    cmd[:1] + ["-no-xattrs"] + cmd[1:],
                    capture_output=True, text=True, check=True, timeout=600,
                )
            except subprocess.CalledProcessError as retry_exc:
                raise ISOError(
                    f"Squashfs extraction failed: {retry_exc.stderr}"
                ) from retry_exc

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
            self.extract_dir / "boot" / "grub" / "efiboot.img",
        ]:
            if candidate.is_file():
                efi_boot = candidate
                break
        if efi_boot is None:
            for img in self.extract_dir.rglob("efiboot.img"):
                efi_boot = img
                break

        efi_rel = str(efi_boot.relative_to(self.extract_dir)) if efi_boot else None

        bios_boot = None
        boot_catalog = None
        for bios_candidate, cat_candidate in [
            ("boot/syslinux/isolinux.bin", "boot/syslinux/boot.cat"),  # Arch
            ("isolinux/isolinux.bin", "isolinux/boot.cat"),            # Mint/Ubuntu
        ]:
            if (self.extract_dir / bios_candidate).is_file():
                bios_boot = bios_candidate
                boot_catalog = cat_candidate
                break

        volid = self.get_iso_label() or "SURFACE_CUSTOM"
        cmd = [
            "xorriso",
            "-as", "mkisofs",
            "-iso-level", "3",
            "-full-iso9660-filenames",
            "-volid", volid,
        ]
        if bios_boot and boot_catalog:
            cmd += [
                "-eltorito-boot", bios_boot,
                "-eltorito-catalog", boot_catalog,
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
        if bios_boot:
            isolinux = self.extract_dir / bios_boot
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
