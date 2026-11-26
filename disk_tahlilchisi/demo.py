"""Skrinshot rejimi uchun namunaviy natija (haqiqiy diskni skanerlamaydi)."""
import os
import random
import time

from .scanner import DirNode, FileRec, ScanResult, aggregate

GB = 1024 ** 3
MB = 1024 ** 2

_TREE = {
    "Users": {"Bahtiyor": {"Videos": [("Toy_2025.mp4", 14.2 * GB), ("Montaj_final.mov", 6.8 * GB),
                                      ("Dars_01.mkv", 2.3 * GB), ("Dars_02.mkv", 2.1 * GB)],
                           "Downloads": [("Windows11_24H2.iso", 5.4 * GB), ("ubuntu-24.04.iso", 5.9 * GB),
                                         ("AutoCAD_2024.exe", 2.9 * GB), ("drivers.zip", 820 * MB)],
                           "Pictures": [("IMG_%04d.jpg" % i, random.Random(i).uniform(3, 9) * MB) for i in range(30)],
                           "Documents": [("Hisobot_2025.xlsx", 18 * MB), ("Shartnoma.pdf", 4 * MB),
                                         ("Loyiha.dwg", 160 * MB), ("Smeta.docx", 2 * MB)],
                           "AppData": {"Local": {"Temp": [("setup_tmp.tmp", 1.2 * GB), ("log1.log", 300 * MB)],
                                                 "Google": [("Cache_data", 2.4 * GB)],
                                                 "Unity": [("cache.bin", 3.1 * GB)]},
                                       "Roaming": {"Adobe": [("MediaCache.cfa", 6.2 * GB)]}}}},
    "Program Files": {"Adobe": [("Premiere.dll", 2.2 * GB), ("Photoshop.exe", 1.1 * GB)],
                      "Autodesk": [("acad.dll", 3.6 * GB)],
                      "Microsoft Office": [("office.dll", 2.7 * GB)]},
    "Windows": {"System32": [("ntoskrnl.exe", 11 * MB), ("drivers.sys", 9.5 * GB)],
                "WinSxS": [("components.cab", 8.4 * GB)], "Temp": [("cab_temp.tmp", 640 * MB)]},
    "Games": {"Steam": [("game_data.pak", 38 * GB), ("textures.pak", 12 * GB)]},
}
_ROOT_FILES = [("pagefile.sys", 12 * GB), ("hiberfil.sys", 6.3 * GB)]


def demo_result(root_path: str = "C:\\") -> ScanResult:
    now = time.time()
    rnd = random.Random(7)
    root = DirNode(root_path)
    top, old, ext = [], [], {}

    def add_files(node, files):
        for name, size in files:
            size = int(size)
            mt = now - rnd.uniform(1, 900) * 86400
            at = mt + rnd.uniform(0, 30) * 86400
            node.files.append(FileRec(name, size, mt, at))
            node.own_size += size
            node.own_count += 1
            x = name.rsplit(".", 1)[-1].lower() if "." in name else "(none)"
            s = ext.setdefault(x, [0, 0])
            s[0] += size
            s[1] += 1
            top.append((size, os.path.join(node.path, name), mt, at))
            if size >= 10 * MB:
                old.append((size, os.path.join(node.path, name), mt, at))

    def build(node, spec):
        if isinstance(spec, list):
            add_files(node, spec)
            return
        for name, sub in spec.items():
            ch = DirNode(name, node)
            ch.mtime = now - rnd.uniform(1, 400) * 86400
            node.children.append(ch)
            build(ch, sub)

    build(root, _TREE)
    add_files(root, _ROOT_FILES)
    aggregate(root)
    top.sort(reverse=True)
    old.sort(reverse=True)
    return ScanResult(root=root, top_files=top[:100], ext_stats=ext, old_candidates=old,
                      errors=3, skipped_links=12, seconds=41.7)
