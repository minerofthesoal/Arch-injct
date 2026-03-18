"""
Distro-specific injection handlers.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from core.kernel import KernelError, download_packages, download_signing_key
from core.surface_devices import LINUX_SURFACE_REPO_NAME, LINUX_SURFACE_REPO_URL
from utils.log import get_logger

log = get_logger(__name__)


class DistroHandler(ABC):
    """Base workflow abstraction for distro-specific ISO handling."""

    name = "unknown"

    def __init__(self, injector):
        self.injector = injector

    @property
    def required_tools(self) -> list[str]:
        return []

    def mount_iso(self):
        self.injector.iso.extract(progress_callback=self.injector._progress_cb)

    def extract_files(self):
        squashfs_path = self.injector.iso.find_squashfs(distro=self.name)
        self.injector.iso.extract_squashfs(
            squashfs_path, progress_callback=self.injector._progress_cb
        )
        return squashfs_path, self.injector.iso.squashfs_dir

    @abstractmethod
    def inject_payload(self, root: Path):
        pass

    def rebuild_iso(self, squashfs_path: Path):
        self.injector.iso.rebuild_squashfs(
            squashfs_path, progress_callback=self.injector._progress_cb
        )
        self.injector.iso.update_sha512(squashfs_path)
        return self.injector.iso.rebuild_iso(
            self.injector.output_path, progress_callback=self.injector._progress_cb
        )


class ArchHandler(DistroHandler):
    """Arch Linux injection handler (existing workflow)."""

    name = "arch"

    @property
    def required_tools(self) -> list[str]:
        return ["curl", "mount", "umount", "chroot"]

    def inject_payload(self, root: Path):
        pkg_cache = self.injector.iso.work_dir / "pkg_cache"
        self.injector._progress(55, "Setting up linux-surface repository...")
        key_path = download_signing_key(pkg_cache)
        self._configure_repo(root)

        self.injector._progress(40, "Downloading Surface kernel packages...")
        package_names = [self.injector.device.kernel_variant] + self.injector.device.extra_packages
        try:
            packages = download_packages(
                self.injector.device, pkg_cache, progress_callback=self.injector._progress_cb
            )
            self.injector._progress(58, "Installing Surface kernel into root filesystem...")
            self.injector._install_into_root(root, packages, key_path)
            return
        except KernelError as exc:
            log.warning(
                "Package file lookup/download failed (%s). "
                "Falling back to in-chroot pacman install from linux-surface repo.",
                exc,
            )
            self.injector._progress(
                58,
                "Falling back to direct in-chroot package install from linux-surface repo...",
            )
            self.injector._install_into_root_from_repo(root, package_names, key_path)

        self.injector._progress(65, "Configured linux-surface repository")

    def _configure_repo(self, root: Path):
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
            pacman_conf.write_text(content + repo_block)
            log.info("Added linux-surface repo to pacman.conf")


class MintHandler(DistroHandler):
    """
    Linux Mint / Ubuntu casper handler.

    Installs a small first-boot payload via casper hook + systemd service.
    """

    name = "mint"

    @property
    def required_tools(self) -> list[str]:
        return []

    def inject_payload(self, root: Path):
        self.injector._progress(40, "Injecting Linux Mint payload...")

        script = root / "usr" / "local" / "sbin" / "surface-injected.sh"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "#!/bin/sh\n"
            "mkdir -p /var/log\n"
            "echo \"surface injector payload executed\" >> /var/log/surface-inject.log\n"
            "touch /var/lib/surface-injected\n"
        )
        script.chmod(0o755)

        service = root / "etc" / "systemd" / "system" / "surface-injected.service"
        service.parent.mkdir(parents=True, exist_ok=True)
        service.write_text(
            "[Unit]\n"
            "Description=Surface ISO injector payload\n"
            "After=multi-user.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/usr/local/sbin/surface-injected.sh\n\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )

        wants = root / "etc" / "systemd" / "system" / "multi-user.target.wants"
        wants.mkdir(parents=True, exist_ok=True)
        target_link = wants / "surface-injected.service"
        if target_link.exists() or target_link.is_symlink():
            target_link.unlink()
        target_link.symlink_to(Path("..") / "surface-injected.service")

        casper_hook = root / "etc" / "casper-bottom" / "99-surface-injected"
        casper_hook.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(script, casper_hook)

        self._patch_mint_boot_configs()
        self.injector._progress(65, "Linux Mint payload injected")

    def _patch_mint_boot_configs(self):
        """
        Add a boot marker parameter for casper-based boots if grub configs are present.
        """
        for cfg in [
            self.injector.iso.extract_dir / "boot" / "grub" / "grub.cfg",
            self.injector.iso.extract_dir / "boot" / "grub" / "loopback.cfg",
        ]:
            if not cfg.is_file():
                continue
            content = cfg.read_text(errors="ignore")
            out: list[str] = []
            changed = False
            for line in content.splitlines():
                lower = line.lower()
                if " boot=casper" in lower and "surface_injected=1" not in lower:
                    out.append(f"{line} surface_injected=1")
                    changed = True
                else:
                    out.append(line)
            if changed:
                cfg.write_text("\n".join(out) + "\n")
                log.info("Patched Mint boot config: %s", cfg)
