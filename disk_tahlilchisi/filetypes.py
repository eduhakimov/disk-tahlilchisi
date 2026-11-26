"""Fayl turlari: kengaytma -> toifa va rang."""
import os

CATEGORIES = {
    # kalit: (rang, kengaytmalar)
    "video": ("#d9534f", "mp4 mkv avi mov wmv flv webm m4v mpg mpeg ts mts m2ts 3gp vob"),
    "image": ("#e8a33d", "jpg jpeg png gif bmp tif tiff webp heic raw cr2 cr3 nef arw dng psd ai svg ico"),
    "audio": ("#b565a7", "mp3 wav flac aac ogg m4a wma opus aiff"),
    "document": ("#4a90d9", "pdf doc docx xls xlsx ppt pptx odt ods odp rtf txt csv md epub djvu"),
    "archive": ("#8d6e63", "zip rar 7z tar gz bz2 xz tgz cab zst"),
    "disk_image": ("#5c6bc0", "iso img vhd vhdx vmdk vdi wim esd swm qcow2"),
    "program": ("#3aa676", "exe msi dll sys ocx msix appx apk jar bat cmd ps1 com"),
    "code": ("#26a69a", "py js ts c cpp h hpp cs java go rs php html css json xml yml yaml sql ipynb"),
    "design": ("#ec7063", "dwg dxf skp max blend fbx obj stl 3ds c4d prproj aep indd"),
    "temp": ("#9e9e9e", "tmp temp log bak old dmp cache etl"),
    "other": ("#78909c", ""),
}

_EXT_MAP = {}
for _cat, (_c, _exts) in CATEGORIES.items():
    for _e in _exts.split():
        _EXT_MAP[_e] = _cat

NO_EXT = "(none)"


def ext_of(name: str) -> str:
    e = os.path.splitext(name)[1].lower().lstrip(".")
    if not e or len(e) > 10 or " " in e:
        return NO_EXT
    return e


def category(name_or_ext: str) -> str:
    e = name_or_ext.lower()
    if "." in e:
        e = ext_of(e)
    return _EXT_MAP.get(e, "other")


def color(cat: str) -> str:
    return CATEGORIES.get(cat, CATEGORIES["other"])[0]


def by_category(ext_stats: dict) -> dict:
    """{ext: [size, count]} -> {category: [size, count]}, kattadan kichikka."""
    out = {}
    for e, (sz, cnt) in ext_stats.items():
        c = _EXT_MAP.get(e, "other")
        s = out.setdefault(c, [0, 0])
        s[0] += sz
        s[1] += cnt
    return dict(sorted(out.items(), key=lambda kv: kv[1][0], reverse=True))
