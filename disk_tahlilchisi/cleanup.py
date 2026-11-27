"""Ma'lum kesh va vaqtinchalik fayl joylari, Savat hajmi, xavfsiz o'chirish (faqat Savatga)."""
import ctypes
import os
import stat
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass
class Location:
    key: str            # tarjima kaliti (loc_*)
    paths: List[str]    # mavjud bo'lgan yo'llar
    size: int = -1
    files: int = 0
    note: str = ""      # tarjima kaliti (ixtiyoriy izoh)
    cleanable: bool = True


def _env(name: str) -> str:
    return os.environ.get(name, "")


def _glob_profiles(base: str, tail: str) -> List[str]:
    """Brauzer profillari: Default, Profile 1, ... ichidagi kesh papkalari."""
    out = []
    if not base or not os.path.isdir(base):
        return out
    try:
        for name in os.listdir(base):
            if name == "Default" or name.startswith("Profile "):
                p = os.path.join(base, name, tail)
                if os.path.isdir(p):
                    out.append(p)
    except OSError:
        pass
    return out


def known_locations(env: Dict[str, str] = None) -> List[Location]:
    """Kompyuterda mavjud bo'lgan kesh/vaqtinchalik joylar ro'yxati."""
    g = (env or os.environ).get
    local = g("LOCALAPPDATA", "")
    roaming = g("APPDATA", "")
    temp = g("TEMP", "")
    windir = g("WINDIR", "C:\\Windows")
    raw = [
        ("loc_user_temp", [temp]),
        ("loc_win_temp", [os.path.join(windir, "Temp")]),
        ("loc_chrome", _glob_profiles(os.path.join(local, "Google", "Chrome", "User Data"), "Cache")
         + _glob_profiles(os.path.join(local, "Google", "Chrome", "User Data"), "Code Cache")),
        ("loc_edge", _glob_profiles(os.path.join(local, "Microsoft", "Edge", "User Data"), "Cache")
         + _glob_profiles(os.path.join(local, "Microsoft", "Edge", "User Data"), "Code Cache")),
        ("loc_yandex", _glob_profiles(os.path.join(local, "Yandex", "YandexBrowser", "User Data"), "Cache")),
        ("loc_firefox", _firefox_caches(local)),
        ("loc_unity", [os.path.join(local, "Unity", "cache"), os.path.join(roaming, "Unity", "Asset Store-5.x"),
                       os.path.join(local, "Unity", "Caches")]),
        ("loc_adobe_media", [os.path.join(roaming, "Adobe", "Common", "Media Cache Files"),
                             os.path.join(roaming, "Adobe", "Common", "Media Cache"),
                             os.path.join(roaming, "Adobe", "Common", "Peak Files")]),
        ("loc_crashdumps", [os.path.join(local, "CrashDumps"), os.path.join(windir, "Minidump")]),
        ("loc_d3d", [os.path.join(local, "D3DSCache"), os.path.join(local, "NVIDIA", "DXCache"),
                     os.path.join(local, "NVIDIA", "GLCache"), os.path.join(local, "AMD", "DxCache")]),
        ("loc_wu", [os.path.join(windir, "SoftwareDistribution", "Download")]),
        ("loc_pip", [os.path.join(local, "pip", "cache"), os.path.join(local, "npm-cache")]),
        ("loc_thumbs", [os.path.join(local, "Microsoft", "Windows", "Explorer")]),
    ]
    out = []
    for key, paths in raw:
        seen = []
        for p in paths:
            if p and os.path.isdir(p) and os.path.normcase(p) not in (os.path.normcase(s) for s in seen):
                seen.append(p)
        if seen:
            note = {"loc_wu": "note_admin", "loc_win_temp": "note_admin",
                    "loc_thumbs": "note_thumbs"}.get(key, "note_close_apps" if key in (
                        "loc_chrome", "loc_edge", "loc_yandex", "loc_firefox", "loc_adobe_media", "loc_unity") else "")
            out.append(Location(key, seen, note=note))
    return out


def _firefox_caches(local: str) -> List[str]:
    base = os.path.join(local, "Mozilla", "Firefox", "Profiles")
    out = []
    if os.path.isdir(base):
        try:
            for name in os.listdir(base):
                p = os.path.join(base, name, "cache2")
                if os.path.isdir(p):
                    out.append(p)
        except OSError:
            pass
    return out


def dir_size(path: str, cancelled: Callable[[], bool] = None) -> Tuple[int, int]:
    """Papka hajmi va fayllar soni (reparse point'larga kirmaydi)."""
    total = files = 0
    stack = [path]
    while stack:
        if cancelled and cancelled():
            break
        p = stack.pop()
        try:
            with os.scandir(p) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if getattr(st, "st_file_attributes", 0) & REPARSE:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(e.path)
                    else:
                        total += st.st_size
                        files += 1
        except OSError:
            continue
    return total, files


# ---------------------------------------------------------------------------- Savat (Recycle Bin)
class _SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]


def recycle_bin_info(root: Optional[str] = None) -> Tuple[int, int]:
    """Savatdagi (barcha disklar yoki bitta disk) fayllar hajmi va soni. Xato bo'lsa (-1, 0)."""
    try:
        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)
        r = ctypes.windll.shell32.SHQueryRecycleBinW(root, ctypes.byref(info))
        if r != 0:
            return -1, 0
        return int(info.i64Size), int(info.i64NumItems)
    except Exception:
        return -1, 0


# ---------------------------------------------------------------------------- xavfsizlik
def _protected_roots() -> List[str]:
    g = os.environ.get
    windir = g("WINDIR", "C:\\Windows")
    roots = [windir, g("ProgramFiles", "C:\\Program Files"), g("ProgramFiles(x86)", "C:\\Program Files (x86)"),
             g("ProgramData", "C:\\ProgramData"), g("USERPROFILE", ""), g("APPDATA", ""), g("LOCALAPPDATA", ""),
             os.path.join(g("SystemDrive", "C:"), os.sep, "Users")]
    return [os.path.normcase(os.path.normpath(r)) for r in roots if r]


def is_protected(path: str) -> bool:
    """O'chirish taqiqlangan joylar: disk ildizi, tizim papkalari va ularning ichi (kesh/temp bundan mustasno),
    shuningdek asosiy foydalanuvchi papkalarining o'zi."""
    if not path:
        return True
    p = os.path.normcase(os.path.normpath(os.path.abspath(path)))
    drive, rest = os.path.splitdrive(p)
    if rest in ("", os.sep, "/"):
        return True
    roots = _protected_roots()
    if p in roots:
        return True
    prof = os.path.normcase(os.path.normpath(os.environ.get("USERPROFILE", "") or "?"))
    if os.path.dirname(p) == prof:      # Desktop, Documents, Downloads, AppData ... ning o'zi
        return True
    if os.path.dirname(p) == roots[-1]:     # C:\Users\<boshqa foydalanuvchi>, Public, Default
        return True
    windir = roots[0]
    allowed_in_windir = [os.path.join(windir, "temp"), os.path.join(windir, "softwaredistribution", "download"),
                         os.path.join(windir, "minidump")]
    for r in roots[:4]:      # Windows, Program Files, Program Files (x86), ProgramData
        if p.startswith(r + os.sep):
            if any(p == a or p.startswith(a + os.sep) for a in allowed_in_windir):
                return False
            return True
    return False


def trash_paths(paths: Iterable[str], trash: Callable[[str], None] = None,
                progress: Callable[[int, str], None] = None) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Fayl/papkalarni FAQAT Savatga yuboradi (send2trash). Himoyalangan yo'llar rad etiladi.

    Qaytaradi: (muvaffaqiyatli, [(yo'l, xato)]).
    """
    if trash is None:
        from send2trash import send2trash as trash
    paths = list(paths)
    ok, failed = [], []
    for i, p in enumerate(paths):
        if progress:
            progress(int(100 * i / max(1, len(paths))), p)
        if is_protected(p):
            failed.append((p, "protected"))
            continue
        if not os.path.lexists(p):
            failed.append((p, "not found"))
            continue
        try:
            trash(p)
            ok.append(p)
        except Exception as ex:   # band fayl, ruxsat yo'q va h.k.
            failed.append((p, str(ex) or ex.__class__.__name__))
    return ok, failed


def contents(folder: str, exclude: Iterable[str] = ()) -> List[str]:
    """Papkaning o'zini emas, ichidagilarini tozalash uchun ro'yxat (exclude dagi yo'llar tashlab ketiladi)."""
    ex = {os.path.normcase(os.path.normpath(e)) for e in exclude if e}
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for n in names:
        p = os.path.join(folder, n)
        if os.path.normcase(os.path.normpath(p)) in ex or n.startswith("_MEI"):
            continue
        out.append(p)
    return out
