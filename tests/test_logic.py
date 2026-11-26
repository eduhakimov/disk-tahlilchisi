import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from disk_tahlilchisi import cleanup
from disk_tahlilchisi.filetypes import by_category, category, ext_of
from disk_tahlilchisi.report import export_csv, export_html, human
from disk_tahlilchisi.scanner import old_files, scan
from disk_tahlilchisi.treemap import squarify


# ---------------------------------------------------------------- treemap
def test_squarify_areas_and_bounds():
    vals = [500, 300, 120, 60, 15, 5]
    rects = squarify(vals, 10, 20, 400, 300)
    total = sum(vals)
    for v, (x, y, w, h) in zip(vals, rects):
        assert abs(w * h - v / total * 400 * 300) < 1e-6
        assert x >= 10 - 1e-9 and y >= 20 - 1e-9
        assert x + w <= 410 + 1e-6 and y + h <= 320 + 1e-6
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            ox = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            oy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            assert ox <= 1e-6 or oy <= 1e-6


def test_squarify_aspect_reasonable_and_zero():
    rects = squarify([1] * 16, 0, 0, 100, 100)
    for x, y, w, h in rects:
        assert max(w / h, h / w) < 2.01
    r = squarify([0, 5, -1], 0, 0, 10, 10)
    assert r[0][2] == 0 and r[2][2] == 0 and abs(r[1][2] * r[1][3] - 100) < 1e-9
    assert squarify([], 0, 0, 10, 10) == []


# ---------------------------------------------------------------- filetypes
def test_filetypes():
    assert ext_of("Film.MKV") == "mkv"
    assert ext_of("README") == "(none)"
    assert category("x.mp4") == "video"
    assert category("iso") == "disk_image"
    assert category("weird.zzz") == "other"
    cats = by_category({"mp4": [100, 1], "mkv": [50, 2], "zzz": [10, 1]})
    assert list(cats) == ["video", "other"] and cats["video"] == [150, 3]


def test_human():
    assert human(0) == "0 B"
    assert human(1536) == "1.5 KB"
    assert human(5 * 1024 ** 3) == "5.0 GB"


# ---------------------------------------------------------------- scanner
def _make_tree(root: Path):
    (root / "a" / "b").mkdir(parents=True)
    (root / "c").mkdir()
    (root / "top.bin").write_bytes(b"x" * 1000)
    (root / "a" / "f1.mp4").write_bytes(b"x" * 3000)
    (root / "a" / "b" / "f2.txt").write_bytes(b"x" * 500)
    for i in range(50):
        (root / "c" / f"s{i}.log").write_bytes(b"x" * (10 + i))


SMALL = sum(10 + i for i in range(50))


def test_scan_totals(tmp_path):
    _make_tree(tmp_path)
    res = scan(str(tmp_path), threads=4)
    assert res.root.size == 1000 + 3000 + 500 + SMALL
    assert res.root.file_count == 53
    assert res.root.dir_count == 3
    a = res.root.find(str(tmp_path / "a"))
    assert a is not None and a.size == 3500 and a.file_count == 2
    c = res.root.find(str(tmp_path / "c"))
    assert len(c.files) == 40 and c.rest_count == 10 and c.own_size == SMALL
    assert res.top_files[0][0] == 3000 and res.top_files[0][1].endswith("f1.mp4")
    assert res.ext_stats["log"] == [SMALL, 50]
    assert res.root.children[0].name == "a"
    assert not res.cancelled


def test_scan_cancel(tmp_path):
    _make_tree(tmp_path)
    res = scan(str(tmp_path), threads=2, cancelled=lambda: True)
    assert res.cancelled and res.root.file_count == 0


def test_scan_missing_path(tmp_path):
    res = scan(str(tmp_path / "nope"))
    assert res.errors == 1 and res.root.size == 0


def test_scan_skips_junction(tmp_path):
    _make_tree(tmp_path)
    target = tmp_path / "a"
    link = tmp_path / "loop"
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("junction could not be created")
    try:
        res = scan(str(tmp_path))
        assert res.skipped_links >= 1
        assert res.root.find(str(link)) is None
        assert res.root.size == 4500 + SMALL
    finally:
        os.rmdir(link)       # faqat junction o'zi o'chadi
    assert (target / "f1.mp4").exists()


def test_old_files():
    now = time.time()
    cands = [(500, "a", now - 400 * 86400, now - 300 * 86400), (500, "b", now - 10 * 86400, now - 1 * 86400),
             (50, "c", now - 900 * 86400, now - 900 * 86400)]
    assert [c[1] for c in old_files(cands, 100, 180, "atime", now)] == ["a"]
    assert [c[1] for c in old_files(cands, 10, 365, "mtime", now)] == ["a", "c"]


# ---------------------------------------------------------------- cleanup
def test_is_protected():
    win = os.environ.get("WINDIR", "C:\\Windows")
    prof = os.environ.get("USERPROFILE")
    assert cleanup.is_protected("C:\\")
    assert cleanup.is_protected("")
    assert cleanup.is_protected(win)
    assert cleanup.is_protected(os.path.join(win, "System32", "drivers"))
    assert not cleanup.is_protected(os.path.join(win, "Temp", "x.tmp"))
    assert cleanup.is_protected(os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "App"))
    assert cleanup.is_protected(prof)
    assert cleanup.is_protected(os.path.join(prof, "Documents"))
    assert not cleanup.is_protected(os.path.join(prof, "Documents", "old.iso"))
    assert not cleanup.is_protected(os.path.join(os.environ["TEMP"], "abc"))


def test_trash_paths_fake(tmp_path):
    f1 = tmp_path / "one.tmp"
    f1.write_text("1")
    calls = []
    ok, failed = cleanup.trash_paths([str(f1), str(tmp_path / "missing"), "C:\\Windows"], trash=calls.append)
    assert ok == [str(f1)] and calls == [str(f1)]
    reasons = dict(failed)
    assert reasons[str(tmp_path / "missing")] == "not found"
    assert reasons["C:\\Windows"] == "protected"


def test_trash_paths_error(tmp_path):
    f1 = tmp_path / "busy.tmp"
    f1.write_text("1")

    def boom(p):
        raise PermissionError("in use")
    ok, failed = cleanup.trash_paths([str(f1)], trash=boom)
    assert ok == [] and failed[0][1] == "in use" and f1.exists()


def test_trash_real_send2trash_in_temp_sandbox(tmp_path):
    """Haqiqiy send2trash faqat %TEMP% dagi sinov faylida."""
    assert os.path.normcase(str(tmp_path)).startswith(os.path.normcase(os.path.realpath(os.environ["TEMP"]))[:3])
    f = tmp_path / "disk_tahlilchisi_test_sandbox.txt"
    f.write_text("sandbox")
    ok, failed = cleanup.trash_paths([str(f)])
    assert ok == [str(f)] and not failed and not f.exists()


def test_contents_and_dir_size(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / "_MEI12345").mkdir()
    items = cleanup.contents(str(tmp_path), exclude=[str(tmp_path / "c")])
    names = sorted(os.path.basename(p) for p in items)
    assert names == ["a", "top.bin"]
    size, n = cleanup.dir_size(str(tmp_path))
    assert n == 53 and size == 4500 + SMALL


def test_known_locations_fake_env(tmp_path):
    local = tmp_path / "Local"
    (local / "Google" / "Chrome" / "User Data" / "Default" / "Cache").mkdir(parents=True)
    (local / "Google" / "Chrome" / "User Data" / "Profile 2" / "Cache").mkdir(parents=True)
    (local / "Unity" / "cache").mkdir(parents=True)
    temp = tmp_path / "Temp"
    temp.mkdir()
    env = {"LOCALAPPDATA": str(local), "APPDATA": str(tmp_path / "Roaming"), "TEMP": str(temp),
           "WINDIR": str(tmp_path / "NoWin")}
    locs = {l.key: l for l in cleanup.known_locations(env)}
    assert set(locs) == {"loc_user_temp", "loc_chrome", "loc_unity"}
    assert len(locs["loc_chrome"].paths) == 2


def test_recycle_bin_info_runs():
    size, n = cleanup.recycle_bin_info()
    assert size >= -1 and n >= 0


# ---------------------------------------------------------------- report
def test_reports(tmp_path):
    _make_tree(tmp_path / "data")
    res = scan(str(tmp_path / "data"))
    c = tmp_path / "r.csv"
    h = tmp_path / "r.html"
    export_csv(res, str(c))
    export_html(res, str(h))
    txt = c.read_text(encoding="utf-8-sig")
    assert "f1.mp4" in txt and "3000" in txt
    html = h.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and "f1.mp4" in html and "cat_video" in html


def test_demo_result():
    from disk_tahlilchisi.demo import demo_result
    r = demo_result()
    assert r.root.size > 100 * 1024 ** 3 and r.top_files and r.old_candidates
