"""
Surface kernel fetching and management.

Downloads and manages linux-surface kernel packages from the
linux-surface Arch repository.
"""

import re
import subprocess
import tempfile
from pathlib import Path

from core.surface_devices import (
    LINUX_SURFACE_KEY_URL,
    LINUX_SURFACE_REPO_NAME,
    LINUX_SURFACE_REPO_URL,
    SurfaceDevice,
)
from utils.log import get_logger

log = get_logger(__name__)


class KernelError(Exception):
    """Raised when kernel operations fail."""


def fetch_latest_kernel_version() -> str:
    """
    Query the linux-surface Arch repo to find the latest kernel version.
    Returns version string like '6.6.7-1'.
    """
    try:
        result = subprocess.run(
            [
                "curl", "-sL",
                f"{LINUX_SURFACE_REPO_URL}x86_64/",
            ],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise KernelError(f"Failed to query linux-surface repo: {exc}") from exc

    # Parse package names like linux-surface-6.6.7-1-x86_64.pkg.tar.zst
    pattern = r"linux-surface-(\d+\.\d+[\.\d]*-\d+)-x86_64\.pkg\.tar\.\w+"
    versions = re.findall(pattern, result.stdout)

    if not versions:
        raise KernelError(
            "Could not find any linux-surface kernel packages in the repository"
        )

    # Sort by version components to find the latest
    def version_key(v: str):
        parts = re.split(r"[.\-]", v)
        return [int(p) for p in parts if p.isdigit()]

    versions.sort(key=version_key, reverse=True)
    latest = versions[0]
    log.info("Latest linux-surface kernel: %s", latest)
    return latest


def get_package_urls(device: SurfaceDevice, version: str | None = None) -> list[str]:
    """
    Build the list of package URLs needed for a given device.
    If version is None, 'latest' glob pattern is used (for pacman).
    """
    base = f"{LINUX_SURFACE_REPO_URL}x86_64/"
    packages = [device.kernel_variant] + device.extra_packages
    urls = [f"{base}{pkg}" for pkg in packages]
    return urls


def download_packages(
    device: SurfaceDevice,
    dest_dir: Path,
    progress_callback=None,
) -> list[Path]:
    """
    Download all needed packages for the device into dest_dir.
    Uses curl to pull from the linux-surface Arch repo.
    Returns list of downloaded .pkg.tar.zst files.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    all_packages = [device.kernel_variant] + device.extra_packages

    downloaded: list[Path] = []

    for i, pkg_name in enumerate(all_packages):
        if progress_callback:
            pct = 40 + int(20 * i / len(all_packages))
            progress_callback(pct, f"Downloading {pkg_name}...")

        log.info("Downloading %s from linux-surface repo...", pkg_name)

        # Use a temporary pacman-style DB sync to grab the package
        # We'll download the package file directly
        try:
            # First, find the exact filename
            result = subprocess.run(
                ["curl", "-sL", f"{LINUX_SURFACE_REPO_URL}x86_64/"],
                capture_output=True, text=True, timeout=30, check=True,
            )

            # Find the matching package file
            pattern = re.escape(pkg_name) + r"-[\d][^\s\"'<>]+-x86_64\.pkg\.tar\.\w+"
            matches = re.findall(pattern, result.stdout)

            if not matches:
                raise KernelError(
                    f"Package {pkg_name} not found in linux-surface repo"
                )

            # Pick the latest version
            def version_key(filename: str):
                parts = re.findall(r"\d+", filename)
                return [int(p) for p in parts]

            matches.sort(key=version_key, reverse=True)
            filename = matches[0]

            pkg_url = f"{LINUX_SURFACE_REPO_URL}x86_64/{filename}"
            pkg_dest = dest_dir / filename

            subprocess.run(
                ["curl", "-L", "-o", str(pkg_dest), pkg_url],
                capture_output=True, text=True, timeout=300, check=True,
            )

            if pkg_dest.is_file() and pkg_dest.stat().st_size > 0:
                downloaded.append(pkg_dest)
                log.info("Downloaded: %s", pkg_dest)
            else:
                raise KernelError(f"Download produced empty file: {pkg_dest}")

        except subprocess.CalledProcessError as exc:
            raise KernelError(
                f"Failed to download {pkg_name}: {exc.stderr}"
            ) from exc

    return downloaded


def download_signing_key(dest_dir: Path) -> Path:
    """Download the linux-surface GPG signing key."""
    key_path = dest_dir / "surface.asc"
    try:
        subprocess.run(
            ["curl", "-sL", "-o", str(key_path), LINUX_SURFACE_KEY_URL],
            capture_output=True, text=True, timeout=30, check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise KernelError(f"Failed to download signing key: {exc}") from exc

    log.info("Downloaded signing key: %s", key_path)
    return key_path
