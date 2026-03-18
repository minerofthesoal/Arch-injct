"""
Surface kernel fetching and management.

Downloads and manages linux-surface kernel packages from the
linux-surface Arch repository.
"""

import re
import subprocess
import tempfile
import tarfile
import urllib.request
import json
from urllib.parse import quote
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


def _version_key(version: str) -> list[int]:
    """
    Convert a package version string into sortable integer chunks.
    """
    return [int(p) for p in re.findall(r"\d+", version)]


def _fetch_repo_metadata_from_github() -> list[tuple[str, str, str]]:
    """
    Fallback metadata source using linux-surface/repo GitHub API directory listings.
    """
    repo_api = "https://api.github.com/repos/linux-surface/repo"
    headers = {"User-Agent": "surface-iso-injector"}

    try:
        req = urllib.request.Request(repo_api, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            repo_info = json.loads(resp.read().decode("utf-8"))
        default_branch = repo_info.get("default_branch", "u/staging")

        content_url = (
            "https://api.github.com/repos/linux-surface/repo/contents/arch"
            f"?ref={quote(default_branch, safe='')}"
        )
        req = urllib.request.Request(content_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            entries = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise KernelError(
            f"Failed to query linux-surface GitHub metadata fallback: {exc}"
        ) from exc

    packages: list[tuple[str, str, str]] = []
    for item in entries:
        name = item.get("name", "")
        if not name.endswith(".pkg.tar.zst.blob"):
            continue

        filename = name.removesuffix(".blob")
        m = re.match(
            r"^(?P<stem>.+)-(?P<rel>\d+)-(?P<arch>x86_64|any)\.pkg\.tar\.\w+$",
            filename,
        )
        if not m:
            continue
        stem = m.group("stem")
        rel = m.group("rel")

        m2 = re.match(r"^(?P<pkg>.+)-(?P<ver>\d[0-9A-Za-z._+]*)$", stem)
        if not m2:
            continue

        pkg_name = m2.group("pkg")
        version = f"{m2.group('ver')}-{rel}"
        packages.append((pkg_name, version, filename))

    if not packages:
        raise KernelError(
            "Could not extract package metadata from linux-surface GitHub repo listing"
        )
    log.info(
        "Using linux-surface metadata fallback from GitHub repo API (%d packages)",
        len(packages),
    )
    return packages


def _fetch_repo_metadata() -> list[tuple[str, str, str]]:
    """
    Read package metadata from linux-surface.db.

    Returns tuples of (package_name, package_version, package_filename).
    """
    repo_db_url = f"{LINUX_SURFACE_REPO_URL}x86_64/{LINUX_SURFACE_REPO_NAME}.db"
    with tempfile.TemporaryDirectory(prefix="surface-db-") as tmp:
        db_path = Path(tmp) / f"{LINUX_SURFACE_REPO_NAME}.db"

        try:
            subprocess.run(
                ["curl", "-sL", "-o", str(db_path), repo_db_url],
                capture_output=True, text=True, timeout=30, check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise KernelError(
                f"Failed to download linux-surface repo database: {exc}"
            ) from exc

        if not db_path.exists() or db_path.stat().st_size == 0:
            log.warning(
                "Downloaded linux-surface repo database is empty (%s); "
                "falling back to GitHub metadata API.",
                repo_db_url,
            )
            return _fetch_repo_metadata_from_github()

        packages: list[tuple[str, str, str]] = []
        try:
            with tarfile.open(db_path, mode="r:*") as tar:
                # pacman DB format: <pkgname-version>/desc
                for member in tar.getmembers():
                    if not member.isfile() or not member.name.endswith("/desc"):
                        continue
                    desc = tar.extractfile(member)
                    if desc is None:
                        continue
                    text = desc.read().decode("utf-8", errors="ignore")
                    fields: dict[str, str] = {}
                    lines = text.splitlines()
                    i = 0
                    while i < len(lines):
                        line = lines[i].strip()
                        if line.startswith("%") and line.endswith("%"):
                            key = line.strip("%")
                            i += 1
                            value_lines: list[str] = []
                            while i < len(lines) and lines[i].strip() != "":
                                value_lines.append(lines[i].strip())
                                i += 1
                            if value_lines:
                                fields[key] = value_lines[0]
                        i += 1

                    name = fields.get("NAME")
                    version = fields.get("VERSION")
                    filename = fields.get("FILENAME")
                    if name and version and filename:
                        packages.append((name, version, filename))
        except tarfile.TarError:
            log.warning(
                "Failed to parse linux-surface repo DB tarball; "
                "falling back to GitHub metadata API."
            )
            return _fetch_repo_metadata_from_github()

        if not packages:
            log.warning(
                "No package entries found in linux-surface DB; "
                "falling back to GitHub metadata API."
            )
            return _fetch_repo_metadata_from_github()

        return packages


def fetch_latest_kernel_version() -> str:
    """
    Query the linux-surface Arch repo to find the latest kernel version.
    Returns version string like '6.6.7-1'.
    """
    packages = _fetch_repo_metadata()
    versions = [version for name, version, _ in packages if name == "linux-surface"]

    if not versions:
        raise KernelError(
            "Could not find any linux-surface kernel packages in the repository"
        )

    versions.sort(key=_version_key, reverse=True)
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
    repo_packages = _fetch_repo_metadata()

    downloaded: list[Path] = []

    for i, pkg_name in enumerate(all_packages):
        if progress_callback:
            pct = 40 + int(20 * i / len(all_packages))
            progress_callback(pct, f"Downloading {pkg_name}...")

        log.info("Downloading %s from linux-surface repo...", pkg_name)

        # Use a temporary pacman-style DB sync to grab the package
        # We'll download the package file directly
        try:
            matches = [
                (version, filename)
                for name, version, filename in repo_packages
                if name == pkg_name
            ]

            if not matches:
                raise KernelError(
                    f"Package {pkg_name} not found in linux-surface repo"
                )

            # Pick the latest package version
            matches.sort(key=lambda x: _version_key(x[0]), reverse=True)
            filename = matches[0][1]

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
    dest_dir.mkdir(parents=True, exist_ok=True)
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
