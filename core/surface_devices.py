"""
Surface device profiles and kernel package mappings.

Maps Microsoft Surface models to their linux-surface kernel package names
and any device-specific firmware/module requirements.
"""

from dataclasses import dataclass, field


@dataclass
class SurfaceDevice:
    name: str
    codename: str
    description: str
    kernel_variant: str = "linux-surface"
    extra_packages: list[str] = field(default_factory=list)
    notes: str = ""


# All supported Surface devices keyed by a short ID
SURFACE_DEVICES: dict[str, SurfaceDevice] = {
    "sp4": SurfaceDevice(
        name="Surface Pro 4",
        codename="SurfacePro4",
        description="Surface Pro 4 (2015) - Intel 6th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sp5": SurfaceDevice(
        name="Surface Pro 5 (2017)",
        codename="SurfacePro2017",
        description="Surface Pro 5th Gen (2017) - Intel 7th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sp6": SurfaceDevice(
        name="Surface Pro 6",
        codename="SurfacePro6",
        description="Surface Pro 6 (2018) - Intel 8th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sp7": SurfaceDevice(
        name="Surface Pro 7",
        codename="SurfacePro7",
        description="Surface Pro 7 (2019) - Intel 10th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sp7plus": SurfaceDevice(
        name="Surface Pro 7+",
        codename="SurfacePro7Plus",
        description="Surface Pro 7+ (2021) - Intel 11th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sp8": SurfaceDevice(
        name="Surface Pro 8",
        codename="SurfacePro8",
        description="Surface Pro 8 (2021) - Intel 11th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sp9intel": SurfaceDevice(
        name="Surface Pro 9 (Intel)",
        codename="SurfacePro9",
        description="Surface Pro 9 Intel (2022) - Intel 12th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sp10": SurfaceDevice(
        name="Surface Pro 10",
        codename="SurfacePro10",
        description="Surface Pro 10 (2024) - Intel Core Ultra",
        extra_packages=["linux-surface-headers", "iptsd"],
        notes="Newer device - check linux-surface compatibility",
    ),
    "sl1": SurfaceDevice(
        name="Surface Laptop 1",
        codename="SurfaceLaptop",
        description="Surface Laptop 1st Gen (2017)",
        extra_packages=["linux-surface-headers"],
    ),
    "sl2": SurfaceDevice(
        name="Surface Laptop 2",
        codename="SurfaceLaptop2",
        description="Surface Laptop 2 (2018) - Intel 8th Gen",
        extra_packages=["linux-surface-headers"],
    ),
    "sl3": SurfaceDevice(
        name="Surface Laptop 3",
        codename="SurfaceLaptop3",
        description="Surface Laptop 3 (2019) - Intel 10th Gen / AMD Ryzen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sl4": SurfaceDevice(
        name="Surface Laptop 4",
        codename="SurfaceLaptop4",
        description="Surface Laptop 4 (2021) - Intel 11th Gen / AMD Ryzen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sl5": SurfaceDevice(
        name="Surface Laptop 5",
        codename="SurfaceLaptop5",
        description="Surface Laptop 5 (2022) - Intel 12th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "slgo": SurfaceDevice(
        name="Surface Laptop Go",
        codename="SurfaceLaptopGo",
        description="Surface Laptop Go (2020)",
        extra_packages=["linux-surface-headers"],
    ),
    "slgo2": SurfaceDevice(
        name="Surface Laptop Go 2",
        codename="SurfaceLaptopGo2",
        description="Surface Laptop Go 2 (2022)",
        extra_packages=["linux-surface-headers"],
    ),
    "slstudio": SurfaceDevice(
        name="Surface Laptop Studio",
        codename="SurfaceLaptopStudio",
        description="Surface Laptop Studio (2021) - Intel 11th Gen + RTX",
        extra_packages=["linux-surface-headers", "iptsd"],
        notes="dGPU support may vary",
    ),
    "slstudio2": SurfaceDevice(
        name="Surface Laptop Studio 2",
        codename="SurfaceLaptopStudio2",
        description="Surface Laptop Studio 2 (2023) - Intel 13th Gen + RTX",
        extra_packages=["linux-surface-headers", "iptsd"],
        notes="dGPU support may vary",
    ),
    "sb1": SurfaceDevice(
        name="Surface Book 1",
        codename="SurfaceBook",
        description="Surface Book 1st Gen (2015)",
        extra_packages=["linux-surface-headers"],
        notes="dGPU detach may not be fully supported",
    ),
    "sb2": SurfaceDevice(
        name="Surface Book 2",
        codename="SurfaceBook2",
        description="Surface Book 2 (2017) - Intel 8th Gen",
        extra_packages=["linux-surface-headers"],
        notes="dGPU detach may not be fully supported",
    ),
    "sb3": SurfaceDevice(
        name="Surface Book 3",
        codename="SurfaceBook3",
        description="Surface Book 3 (2020) - Intel 10th Gen",
        extra_packages=["linux-surface-headers", "iptsd"],
        notes="dGPU detach may not be fully supported",
    ),
    "sg": SurfaceDevice(
        name="Surface Go 1",
        codename="SurfaceGo",
        description="Surface Go 1st Gen (2018) - Pentium Gold",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sg2": SurfaceDevice(
        name="Surface Go 2",
        codename="SurfaceGo2",
        description="Surface Go 2 (2020)",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "sg3": SurfaceDevice(
        name="Surface Go 3",
        codename="SurfaceGo3",
        description="Surface Go 3 (2021)",
        extra_packages=["linux-surface-headers", "iptsd"],
    ),
    "ss": SurfaceDevice(
        name="Surface Studio (Desktop)",
        codename="SurfaceStudio",
        description="Surface Studio desktop - limited support",
        extra_packages=["linux-surface-headers"],
        notes="Desktop Surface - community support only",
    ),
}

LINUX_SURFACE_REPO_URL = "https://pkg.surfacelinux.com/arch/"
LINUX_SURFACE_KEY_URL = (
    "https://raw.githubusercontent.com/linux-surface/linux-surface"
    "/master/pkg/keys/surface.asc"
)
LINUX_SURFACE_REPO_NAME = "linux-surface"


def get_device(device_id: str) -> SurfaceDevice | None:
    return SURFACE_DEVICES.get(device_id)


def list_devices() -> list[tuple[str, SurfaceDevice]]:
    return sorted(SURFACE_DEVICES.items(), key=lambda x: x[1].name)


def get_device_categories() -> dict[str, list[tuple[str, SurfaceDevice]]]:
    categories: dict[str, list[tuple[str, SurfaceDevice]]] = {
        "Surface Pro": [],
        "Surface Laptop": [],
        "Surface Book": [],
        "Surface Go": [],
        "Surface Other": [],
    }
    for dev_id, dev in sorted(SURFACE_DEVICES.items(), key=lambda x: x[1].name):
        placed = False
        for cat in categories:
            if cat != "Surface Other" and dev.name.startswith(cat):
                categories[cat].append((dev_id, dev))
                placed = True
                break
        if not placed:
            categories["Surface Other"].append((dev_id, dev))
    return {k: v for k, v in categories.items() if v}
