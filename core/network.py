"""
Networking helpers for chroot/package-install workflows.
"""

from __future__ import annotations

import socket
from pathlib import Path

from utils.log import get_logger

log = get_logger(__name__)

NETWORK_ERROR = "NETWORK_ERROR"
DNS_ERROR = "DNS_ERROR"
MIRROR_ERROR = "MIRROR_ERROR"


def classify_pacman_error(output: str) -> str | None:
    """Classify common pacman network failures."""
    out = output.lower()
    if "could not resolve host" in out or "temporary failure in name resolution" in out:
        return DNS_ERROR
    if "failed to connect" in out or "connection timed out" in out:
        return NETWORK_ERROR
    if "failed retrieving file" in out or "failed to synchronize all databases" in out:
        return MIRROR_ERROR
    return None


def host_network_status() -> dict[str, bool]:
    """
    Check basic host network + DNS status.
    """
    status = {"internet": False, "dns": False}

    # Raw connectivity (socket to public resolver).
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=3):
            status["internet"] = True
    except OSError:
        status["internet"] = False

    # DNS lookup.
    try:
        socket.gethostbyname("archlinux.org")
        status["dns"] = True
    except OSError:
        status["dns"] = False

    return status


def ensure_resolv_conf(chroot_root: Path):
    """
    Ensure chroot has a usable /etc/resolv.conf.
    """
    etc_dir = chroot_root / "etc"
    etc_dir.mkdir(parents=True, exist_ok=True)
    resolv = etc_dir / "resolv.conf"

    nameserver_fallback = "nameserver 8.8.8.8\nnameserver 1.1.1.1\n"

    try:
        host_resolv = Path("/etc/resolv.conf")
        if host_resolv.is_file() and host_resolv.read_text().strip():
            content = host_resolv.read_text()
            if "nameserver" not in content:
                content = nameserver_fallback
            resolv.write_text(content)
            log.info(
                "netfix event=ensure_resolv_conf status=host_copy target=%s",
                resolv,
            )
            return
    except OSError:
        pass

    try:
        resolv.write_text(nameserver_fallback)
        log.info(
            "netfix event=ensure_resolv_conf status=fallback_public_dns target=%s",
            resolv,
        )
    except OSError as exc:
        log.warning(
            "netfix event=ensure_resolv_conf status=failed target=%s error=%s",
            resolv,
            exc,
        )


def apply_fallback_mirrorlist(chroot_root: Path):
    """
    Write a conservative fallback Arch mirrorlist.
    """
    mirrorlist = chroot_root / "etc" / "pacman.d" / "mirrorlist"
    mirrorlist.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "## surface-iso-injector fallback mirrorlist\n"
        "Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch\n"
        "Server = https://mirror.rackspace.com/archlinux/$repo/os/$arch\n"
        "Server = https://mirrors.kernel.org/archlinux/$repo/os/$arch\n"
    )
    try:
        mirrorlist.write_text(content)
        log.info(
            "netfix event=mirrorlist status=fallback_written target=%s",
            mirrorlist,
        )
    except OSError as exc:
        log.warning(
            "netfix event=mirrorlist status=failed target=%s error=%s",
            mirrorlist,
            exc,
        )

