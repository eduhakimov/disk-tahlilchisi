"""Disklar ro'yxati va band/bo'sh joy."""
from dataclasses import dataclass
from typing import List


@dataclass
class DriveInfo:
    mount: str
    label: str
    fstype: str
    total: int
    used: int
    free: int
    removable: bool = False

    @property
    def percent(self) -> float:
        return 100.0 * self.used / self.total if self.total else 0.0


def _label(mount: str) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        if ctypes.windll.kernel32.GetVolumeInformationW(mount, buf, 261, None, None, None, None, 0):
            return buf.value
    except Exception:
        pass
    return ""


def list_drives() -> List[DriveInfo]:
    import psutil
    out = []
    try:
        parts = psutil.disk_partitions(all=False)
    except Exception:
        return out
    for p in parts:
        if "cdrom" in p.opts or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except Exception:
            continue
        out.append(DriveInfo(p.mountpoint, _label(p.mountpoint), p.fstype, u.total, u.used, u.free,
                             "removable" in p.opts))
    return out
