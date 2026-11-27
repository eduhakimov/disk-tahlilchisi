"""Uchidan-uchiga: sandbox daraxtini skanerlash, hisobot, Savatga yuborish (soxta send2trash) va himoya.

Haqiqiy fayllarga tegilmaydi: hamma narsa tmp_path (TEMP) da, Savatga yuborish soxta funksiya bilan.
"""
import os
import stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from disk_tahlilchisi import cleanup, report
from disk_tahlilchisi.scanner import scan


def _tree(root: Path) -> int:
    files = {
        "Видео & фото/Toy o'tkazildi 2024.mp4": 7000,
        "Видео & фото/rasm.jpg": 1200,
        "Hujjatlar/Hisobot (yakuniy).docx": 800,
        "Hujjatlar/eski/arxiv.zip": 3000,
        "bo'sh papka/.keep": 0,
        "readonly.iso": 5000,
    }
    for rel, size in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    os.chmod(root / "readonly.iso", stat.S_IREAD)
    return sum(files.values())


def test_scan_unicode_tree_and_reports(tmp_path):
    total = _tree(tmp_path)
    try:
        res = scan(str(tmp_path), threads=3)
        assert res.root.size == total and res.root.file_count == 6 and res.errors == 0
        vid = res.root.find(str(tmp_path / "Видео & фото"))
        assert vid.size == 8200 and vid.file_count == 2
        assert res.top_files[0][1].endswith("Toy o'tkazildi 2024.mp4")
        h = tmp_path.parent / f"{tmp_path.name}_rep.html"
        report.export_html(res, str(h))
        text = h.read_text(encoding="utf-8")
        assert "Видео &amp; фото" in text and "Toy o&#x27;tkazildi" in text
        c = tmp_path.parent / f"{tmp_path.name}_rep.csv"
        report.export_csv(res, str(c))
        assert "arxiv.zip" in c.read_text(encoding="utf-8-sig")
    finally:
        os.chmod(tmp_path / "readonly.iso", stat.S_IWRITE | stat.S_IREAD)


def test_other_user_profiles_are_protected(monkeypatch):
    monkeypatch.setenv("SystemDrive", "C:")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\Ali")
    assert cleanup.is_protected(r"C:\Users\Vali")
    assert cleanup.is_protected(r"C:\Users\Public")
    assert not cleanup.is_protected(r"C:\Users\Vali\Downloads\film.mkv")
    assert cleanup.is_protected(r"C:\Users\Ali\Desktop")


def _wait(cond, timeout=10.0):
    from PySide6.QtWidgets import QApplication
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_ui_scan_then_trash_selected(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from uzkit import app as appmod, i18n
    from uzkit.settings import Settings
    appmod.META = appmod.load_meta()
    appmod.SETTINGS = Settings(appmod.META["slug"] + "_test")
    QApplication.instance() or QApplication([])
    i18n.set_language("en")
    import send2trash
    from disk_tahlilchisi import window as W
    trashed = []
    monkeypatch.setattr(send2trash, "send2trash", lambda p: trashed.append(p))
    monkeypatch.setattr(W, "ask", lambda *a, **k: True)
    msgs = []
    monkeypatch.setattr(W, "info", lambda *a, **k: msgs.append(a[1]))
    monkeypatch.setattr(W, "error", lambda *a, **k: msgs.append(a[1]))
    total = _tree(tmp_path)
    try:
        win = W.MainWindow()
        win.start_scan(str(tmp_path))
        win.start_scan(str(tmp_path))                  # ikkinchi bosish: "skanerlash davom etmoqda"
        assert _wait(lambda: win.worker is None and win.result is not None)
        assert win.result.root.size == total
        page = win.largest_page
        assert page.table.rowCount() >= 5
        page.table.selectRow(0)
        page._trash()
        assert trashed == [str(tmp_path / "Видео & фото" / "Toy o'tkazildi 2024.mp4")]
        assert not win.trash([(os.environ.get("WINDIR", r"C:\Windows"), 0)])   # himoyalangan: rad etiladi
        assert len(trashed) == 1
        win.close()
    finally:
        os.chmod(tmp_path / "readonly.iso", stat.S_IWRITE | stat.S_IREAD)
