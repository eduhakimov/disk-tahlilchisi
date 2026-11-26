"""Asosiy oyna: yuqorida asboblar paneli (joy, skanerlash, hisobot), pastda tahlil varaqlari."""
import os
import sys
import time
from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QMenu, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from uzkit import app as appmod
from uzkit.i18n import register, tr
from uzkit.widgets import Card, Worker, ask, error, header, info, open_path, primary_button, reveal_in_explorer, run_worker
from uzkit.window import BaseMainWindow

from . import cleanup
from .drives import list_drives
from .filetypes import by_category, category, color as cat_color, CATEGORIES
from .report import default_name, export_csv, export_html, human
from .scanner import DirNode, ScanResult, old_files, scan as run_scan
from .strings import STRINGS
from .views import CategoryChart, ShareDelegate, TreemapView, UsageBar, current_colors, icon

register(STRINGS)

SCREENSHOT = "--screenshot" in sys.argv
SORT_ROLE = Qt.UserRole + 5


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _date(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OSError, ValueError, OverflowError):
        return ""


class SortTreeItem(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.data(col, SORT_ROLE), other.data(col, SORT_ROLE)
        if a is not None and b is not None:
            return a < b
        return self.text(col).lower() < other.text(col).lower()


class SortTableItem(QTableWidgetItem):
    def __lt__(self, other):
        a, b = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if a is not None and b is not None:
            return a < b
        return self.text().lower() < other.text().lower()


def _item(text: str, sort=None, align_right=False) -> SortTableItem:
    it = SortTableItem(text)
    if sort is not None:
        it.setData(SORT_ROLE, sort)
    if align_right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def _table(cols, stretch=0) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(28)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.setSortingEnabled(True)
    t.setWordWrap(False)
    h = t.horizontalHeader()
    h.setHighlightSections(False)
    h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for i in range(len(cols)):
        h.setSectionResizeMode(i, QHeaderView.Stretch if i == stretch else QHeaderView.ResizeToContents)
    return t


def _tool(icon_name: str, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(icon(icon_name))
    b.setIconSize(QSize(18, 18))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    b.setProperty("iconName", icon_name)
    return b


def _btn(text: str, icon_name: str = None, danger=False) -> QPushButton:
    b = QPushButton(text)
    if icon_name:
        b.setIcon(icon(icon_name))
        b.setProperty("iconName", icon_name)
    if danger:
        b.setObjectName("DangerSoft")
    b.setCursor(Qt.PointingHandCursor)
    return b


# =========================================================================== Disklar
class DriveCard(QFrame):
    def __init__(self, win, d):
        super().__init__()
        self.setObjectName("DriveCard")
        self.setMinimumWidth(250)
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 14, 16, 14)
        l.setSpacing(8)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icon("usb" if d.removable else "drive", current_colors()["muted"], 28).pixmap(28, 28))
        top.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(d.mount.rstrip("\\"))
        t.setObjectName("DriveLetter")
        name = d.label or tr("removable" if d.removable else "local_disk")
        s = QLabel(f"{name}  ·  {d.fstype}")
        s.setObjectName("Muted")
        col.addWidget(t)
        col.addWidget(s)
        top.addLayout(col, 1)
        pct = QLabel(tr("used_pct", pct=f"{d.percent:.0f}"))
        pct.setObjectName("Muted")
        top.addWidget(pct, 0, Qt.AlignTop)
        l.addLayout(top)
        l.addWidget(UsageBar(d.percent))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("free_of", free=human(d.free), total=human(d.total))), 1)
        b = _btn(tr("scan"), "scan")
        b.clicked.connect(lambda: win.start_scan(d.mount))
        row.addWidget(b)
        l.addLayout(row)


class DrivesPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(header(tr("drives_title"), tr("drives_sub")), 1)
        self.refresh_btn = _btn(tr("refresh"), "refresh")
        self.refresh_btn.clicked.connect(self.reload)
        top.addWidget(self.refresh_btn, 0, Qt.AlignBottom)
        lay.addLayout(top)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setObjectName("Plain")
        self.area.viewport().setObjectName("Plain")
        self.holder = QWidget()
        self.holder.setObjectName("Plain")
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.area.setWidget(self.holder)
        lay.addWidget(self.area, 1)

        quick = Card(tr("quick_title"))
        ql = QHBoxLayout()
        ql.setSpacing(8)
        home = os.path.expanduser("~")
        for key, sub in (("qf_downloads", "Downloads"), ("qf_desktop", "Desktop"), ("qf_documents", "Documents"),
                         ("qf_videos", "Videos"), ("qf_pictures", "Pictures"), ("qf_appdata", "AppData")):
            p = os.path.join(home, sub)
            b = _btn(tr(key), "folder")
            b.setEnabled(os.path.isdir(p))
            b.setToolTip(p)
            b.clicked.connect(lambda _=False, x=p: self.win.start_scan(x))
            ql.addWidget(b)
        ql.addStretch(1)
        quick.add(ql)
        lay.addWidget(quick)
        self.reload()

    def reload(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        drives = list_drives()
        if not drives:
            lbl = QLabel(tr("no_drives"))
            lbl.setObjectName("Muted")
            self.grid.addWidget(lbl, 0, 0)
            return
        for i, d in enumerate(drives):
            self.grid.addWidget(DriveCard(self.win, d), i // 2, i % 2)
        self.grid.setRowStretch((len(drives) + 1) // 2, 1)


# =========================================================================== Xarita
class MapPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 16)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.up_btn = _tool("up", tr("up"))
        self.up_btn.clicked.connect(self.go_up)
        bar.addWidget(self.up_btn)
        self.crumbs = QHBoxLayout()
        self.crumbs.setSpacing(0)
        bar.addLayout(self.crumbs)
        bar.addStretch(1)
        self.node_info = QLabel("")
        self.node_info.setObjectName("Muted")
        bar.addWidget(self.node_info)
        lay.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(12)
        frame = QFrame()
        frame.setObjectName("MapFrame")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(1, 1, 1, 1)
        self.map = TreemapView()
        fl.addWidget(self.map)
        body.addWidget(frame, 1)
        self.legend = Card(tr("legend"))
        self.legend.setFixedWidth(210)
        self.legend_rows = QVBoxLayout()
        self.legend_rows.setSpacing(4)
        self.legend.add(self.legend_rows)
        self.legend.lay.addStretch(1)
        body.addWidget(self.legend)
        lay.addLayout(body, 1)
        self.map.open_dir.connect(self.open_node)
        self.map.hovered.connect(lambda p: self.win.status(p, 3000))
        self.map.context.connect(self._context)
        self.set_node(None)

    def set_node(self, node):
        self.node = node
        self.map.set_node(node)
        self.up_btn.setEnabled(node is not None and node.parent is not None)
        while self.crumbs.count():
            w = self.crumbs.takeAt(0).widget()
            if w:
                w.deleteLater()
        if node is None:
            self.node_info.setText("")
            return
        chain = []
        n = node
        while n is not None:
            chain.append(n)
            n = n.parent
        chain.reverse()
        if len(chain) > 6:
            chain = chain[:1] + [None] + chain[-4:]
        for i, n in enumerate(chain):
            if i:
                sep = QLabel("/")
                sep.setObjectName("CrumbSep")
                self.crumbs.addWidget(sep)
            if n is None:
                b = QLabel("...")
                b.setObjectName("Muted")
                self.crumbs.addWidget(b)
                continue
            b = QPushButton(n.name.rstrip("\\") or n.name)
            b.setObjectName("Crumb")
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(n is not node)
            b.clicked.connect(lambda _=False, x=n: self.open_node(x))
            self.crumbs.addWidget(b)
        self.node_info.setText(f"{human(node.size)}   {_num(node.file_count)} {tr('rep_files')}")

    def open_node(self, node):
        self.set_node(node)

    def go_up(self):
        if self.node is not None and self.node.parent is not None:
            self.set_node(self.node.parent)

    def set_legend(self, res):
        while self.legend_rows.count():
            it = self.legend_rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if res is None:
            return
        for cat, (sz, _cnt) in list(by_category(res.ext_stats).items())[:11]:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            sw = QFrame()
            sw.setFixedSize(12, 12)
            sw.setStyleSheet(f"background:{cat_color(cat)}; border-radius:2px; border:none;")
            h.addWidget(sw)
            h.addWidget(QLabel(tr("cat_" + cat)), 1)
            v = QLabel(human(sz))
            v.setObjectName("Muted")
            h.addWidget(v)
            self.legend_rows.addWidget(row)

    def _context(self, cell, pos):
        m = QMenu(self)
        a = m.addAction(icon("open"), tr("show_in_explorer"))
        a.triggered.connect(lambda: reveal_in_explorer(cell.path) if cell.kind != "rest" else open_path(cell.path))
        if cell.kind == "dir":
            m.addAction(icon("scan"), tr("open_here")).triggered.connect(lambda: self.open_node(cell.obj))
        if cell.kind in ("dir", "file"):
            m.addSeparator()
            m.addAction(icon("trash"), tr("to_trash")).triggered.connect(
                lambda: self.win.trash([(cell.path, cell.size)]))
        m.exec(pos)


# =========================================================================== Papkalar
class FoldersPage(QWidget):
    COLS = ("col_name", "col_size", "col_percent", "col_files", "col_modified")

    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 16)
        lay.setSpacing(8)
        hint = QLabel(tr("folders_hint"))
        hint.setObjectName("Muted")
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLS))
        self.tree.setHeaderLabels([tr(c) for c in self.COLS])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.setItemDelegateForColumn(2, ShareDelegate(self.tree))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        h = self.tree.header()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in ((1, 100), (2, 170), (3, 90), (4, 110)):
            h.setSectionResizeMode(i, QHeaderView.Interactive)
            h.resizeSection(i, w)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemDoubleClicked.connect(self._open_on_map)
        lay.addWidget(self.tree, 1)

    def _make(self, parent_size: int, name: str, size: int, files, mtime, node=None, path="") -> SortTreeItem:
        it = SortTreeItem()
        it.setText(0, name)
        if node is not None:
            it.setIcon(0, icon("folder", current_colors()["muted"], 16))
        it.setData(0, SORT_ROLE, None)
        it.setText(1, human(size))
        it.setData(1, SORT_ROLE, size)
        it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        pct = 100.0 * size / parent_size if parent_size else 0.0
        it.setData(2, ShareDelegate.ROLE, pct)
        it.setData(2, SORT_ROLE, pct)
        it.setText(3, _num(files) if files is not None else "")
        it.setData(3, SORT_ROLE, files if files is not None else -1)
        it.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
        it.setText(4, _date(mtime) if mtime else "")
        it.setData(4, SORT_ROLE, mtime or 0)
        it.setData(0, Qt.UserRole, node)
        it.setData(0, Qt.UserRole + 1, path)
        if node is not None and (node.children or node.files or node.rest_size):
            it.addChild(QTreeWidgetItem(["..."]))
        return it

    def set_result(self, res):
        self.tree.clear()
        if res is None:
            return
        root = res.root
        it = self._make(root.size, root.path, root.size, root.file_count, root.mtime, root, root.path)
        it.setData(2, ShareDelegate.ROLE, 100.0)
        self.tree.addTopLevelItem(it)
        self.tree.sortByColumn(1, Qt.DescendingOrder)
        it.setExpanded(True)

    def _expand(self, item):
        node = item.data(0, Qt.UserRole)
        if node is None or item.data(0, Qt.UserRole + 2):
            return
        item.setData(0, Qt.UserRole + 2, True)
        item.takeChildren()
        kids = []
        for c in node.children:
            kids.append(self._make(node.size, c.name, c.size, c.file_count, c.mtime, c, c.path))
        for f in node.files:
            kids.append(self._make(node.size, f[0], f[1], None, f[2], None, os.path.join(node.path, f[0])))
        if node.rest_size:
            kids.append(self._make(node.size, tr("small_files", n=node.rest_count), node.rest_size, node.rest_count,
                                   0, None, node.path))
        item.addChildren(kids)

    def _open_on_map(self, item, _col):
        node = item.data(0, Qt.UserRole)
        if node is not None:
            self.win.show_on_map(node)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        path = item.data(0, Qt.UserRole + 1)
        node = item.data(0, Qt.UserRole)
        m = QMenu(self)
        m.addAction(icon("open"), tr("show_in_explorer")).triggered.connect(lambda: reveal_in_explorer(path))
        if node is not None:
            m.addAction(icon("scan"), tr("open_here")).triggered.connect(lambda: self.win.show_on_map(node))
        if node is None or node.parent is not None:
            size = item.data(1, SORT_ROLE) or 0
            m.addSeparator()
            m.addAction(icon("trash"), tr("to_trash")).triggered.connect(lambda: self.win.trash([(path, size)]))
        m.exec(self.tree.viewport().mapToGlobal(pos))


# =========================================================================== Fayl jadvallari (umumiy)
class FileTablePage(QWidget):
    def __init__(self, win, hint_key: str, cols):
        super().__init__()
        self.win = win
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 14, 20, 16)
        self.lay.setSpacing(8)
        self.top = QHBoxLayout()
        self.hint = QLabel(tr(hint_key))
        self.hint.setObjectName("Muted")
        self.top.addWidget(self.hint, 1)
        self.lay.addLayout(self.top)
        self.table = _table([tr(c) for c in cols])
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(lambda _i: self._reveal())
        self.table.sortByColumn(1, Qt.DescendingOrder)
        self.lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("Muted")
        row.addWidget(self.footer, 1)
        self.open_btn = _btn(tr("open_folder_btn"), "open")
        self.open_btn.clicked.connect(self._reveal)
        self.trash_btn = _btn(tr("to_trash"), "trash", danger=True)
        self.trash_btn.clicked.connect(self._trash)
        row.addWidget(self.open_btn)
        row.addWidget(self.trash_btn)
        self.lay.addLayout(row)

    def fill(self, rows):
        """rows: [(size, path, mtime, atime)]"""
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (sz, path, mt, at) in enumerate(rows):
            name = os.path.basename(path)
            it = _item(name)
            it.setData(Qt.UserRole, path)
            it.setData(Qt.UserRole + 1, sz)
            it.setToolTip(path)
            t.setItem(i, 0, it)
            t.setItem(i, 1, _item(human(sz), sz, True))
            self.fill_rest(i, path, mt, at)
        t.setSortingEnabled(True)

    def fill_rest(self, i, path, mt, at):
        pass

    def selected(self):
        out = []
        for r in sorted({i.row() for i in self.table.selectedIndexes()}):
            it = self.table.item(r, 0)
            if it is not None:
                out.append((it.data(Qt.UserRole), it.data(Qt.UserRole + 1) or 0))
        return out

    def _reveal(self):
        sel = self.selected()
        if sel:
            reveal_in_explorer(sel[0][0])

    def _trash(self):
        sel = self.selected()
        if not sel:
            info(self, tr("nothing_selected"))
            return
        if self.win.trash(sel):
            gone = {p for p, _ in sel if not os.path.exists(p)}
            for r in range(self.table.rowCount() - 1, -1, -1):
                it = self.table.item(r, 0)
                if it is not None and it.data(Qt.UserRole) in gone:
                    self.table.removeRow(r)

    def _menu(self, pos):
        if not self.selected():
            return
        m = QMenu(self)
        m.addAction(icon("open"), tr("show_in_explorer")).triggered.connect(self._reveal)
        m.addSeparator()
        m.addAction(icon("trash"), tr("to_trash")).triggered.connect(self._trash)
        m.exec(self.table.viewport().mapToGlobal(pos))


class LargestPage(FileTablePage):
    def __init__(self, win):
        super().__init__(win, "largest_hint", ("col_name", "col_size", "col_type", "col_modified", "col_folder"))
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.resizeSection(0, 300)
        h.setSectionResizeMode(4, QHeaderView.Stretch)

    def fill_rest(self, i, path, mt, at):
        cat = category(os.path.basename(path))
        self.table.setItem(i, 2, _item(tr("cat_" + cat)))
        self.table.setItem(i, 3, _item(_date(mt), mt))
        self.table.setItem(i, 4, _item(os.path.dirname(path)))

    def set_result(self, res):
        self.fill(res.top_files if res else [])
        if res:
            self.footer.setText(tr("old_found", n=len(res.top_files), size=human(sum(r[0] for r in res.top_files))))
        else:
            self.footer.setText("")


class OldPage(FileTablePage):
    def __init__(self, win):
        super().__init__(win, "old_note", ("col_name", "col_size", "col_accessed", "col_modified", "col_folder"))
        self.res = None
        s = win.settings
        self.hint.setWordWrap(True)
        ctr = QHBoxLayout()
        ctr.setSpacing(8)
        ctr.addWidget(QLabel(tr("old_min_size")))
        self.min_mb = QSpinBox()
        self.min_mb.setRange(10, 100000)
        self.min_mb.setSingleStep(50)
        self.min_mb.setSuffix(" MB")
        self.min_mb.setValue(int(s.get("old_min_mb", 100)) if s else 100)
        ctr.addWidget(self.min_mb)
        ctr.addSpacing(12)
        self.by = QComboBox()
        self.by.addItem(tr("by_access"), "atime")
        self.by.addItem(tr("by_modify"), "mtime")
        self.by.setCurrentIndex(1 if (s and s.get("old_by") == "mtime") else 0)
        ctr.addWidget(self.by)
        self.days_lbl = QLabel()
        ctr.addWidget(self.days_lbl)
        self.days = QSpinBox()
        self.days.setRange(7, 3650)
        self.days.setSingleStep(30)
        self.days.setSuffix(tr("days_sfx"))
        self.days.setValue(int(s.get("old_days", 180)) if s else 180)
        ctr.addWidget(self.days)
        ctr.addStretch(1)
        self.lay.insertLayout(0, ctr)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.resizeSection(0, 280)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        for w in (self.min_mb, self.days):
            w.valueChanged.connect(self.refilter)
        self.by.currentIndexChanged.connect(self.refilter)
        self._set_days_label()

    def _set_days_label(self):
        self.days_lbl.setText(tr("old_days") if self.by.currentData() == "atime" else tr("old_days_mod"))

    def fill_rest(self, i, path, mt, at):
        self.table.setItem(i, 2, _item(_date(at), at))
        self.table.setItem(i, 3, _item(_date(mt), mt))
        self.table.setItem(i, 4, _item(os.path.dirname(path)))

    def set_result(self, res):
        self.res = res
        self.refilter()

    def refilter(self):
        self._set_days_label()
        s = self.win.settings
        if s and not SCREENSHOT:
            s.set("old_min_mb", self.min_mb.value(), save=False)
            s.set("old_days", self.days.value(), save=False)
            s.set("old_by", self.by.currentData())
        if self.res is None:
            self.fill([])
            self.footer.setText("")
            return
        rows = old_files(self.res.old_candidates, self.min_mb.value() * 1024 * 1024, self.days.value(),
                         self.by.currentData())
        rows = [r for r in rows if os.path.exists(r[1]) or SCREENSHOT][:2000]
        self.fill(rows)
        self.footer.setText(tr("old_found", n=len(rows), size=human(sum(r[0] for r in rows))))


# =========================================================================== Fayl turlari
class TypesPage(QWidget):
    def __init__(self, win):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 16)
        sp = QSplitter(Qt.Horizontal)
        left = Card(tr("by_category"))
        self.chart = CategoryChart()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setObjectName("Plain")
        sc.viewport().setObjectName("Plain")
        sc.setWidget(self.chart)
        left.add(sc)
        right = Card(tr("by_ext"))
        self.table = _table([tr("col_ext"), tr("col_type"), tr("col_size"), tr("col_files"), tr("col_percent")], 1)
        self.table.setItemDelegateForColumn(4, ShareDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.horizontalHeader().resizeSection(4, 150)
        right.add(self.table)
        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(0, 5)
        sp.setStretchFactor(1, 6)
        lay.addWidget(sp)

    def set_result(self, res):
        if res is None:
            self.chart.set_rows([])
            self.table.setRowCount(0)
            return
        cats = by_category(res.ext_stats)
        self.chart.set_rows([(tr("cat_" + c), sz, cat_color(c), cnt) for c, (sz, cnt) in cats.items()])
        total = res.total_size or 1
        items = sorted(res.ext_stats.items(), key=lambda kv: kv[1][0], reverse=True)[:500]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(items))
        for i, (ext, (sz, cnt)) in enumerate(items):
            t.setItem(i, 0, _item("." + ext if ext != "(none)" else ext))
            t.setItem(i, 1, _item(tr("cat_" + category(ext))))
            t.setItem(i, 2, _item(human(sz), sz, True))
            t.setItem(i, 3, _item(_num(cnt), cnt, True))
            share = _item("", 100.0 * sz / total)
            share.setData(ShareDelegate.ROLE, 100.0 * sz / total)
            t.setItem(i, 4, share)
        t.setSortingEnabled(True)
        t.sortByColumn(2, Qt.DescendingOrder)


# =========================================================================== Tozalash
class CleanPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.locs = []
        self.worker = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(12)
        lay.addWidget(header(tr("clean_title"), tr("clean_sub")))
        self.table = _table([tr("col_location"), tr("col_size"), tr("col_files"), tr("col_note")], 0)
        self.table.setSortingEnabled(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        lay.addWidget(self.table, 1)

        rb = QFrame()
        rb.setObjectName("RecycleStrip")
        rl = QHBoxLayout(rb)
        rl.setContentsMargins(14, 10, 14, 10)
        ic = QLabel()
        ic.setPixmap(icon("trash", current_colors()["muted"], 22).pixmap(22, 22))
        rl.addWidget(ic)
        self.rb_label = QLabel("")
        self.rb_label.setWordWrap(True)
        rl.addWidget(self.rb_label, 1)
        ob = _btn(tr("recycle_open"), "open")
        ob.clicked.connect(lambda: open_path("shell:RecycleBinFolder"))
        rl.addWidget(ob)
        lay.addWidget(rb)

        row = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("Muted")
        row.addWidget(self.footer, 1)
        self.measure_btn = _btn(tr("measure"), "measure")
        self.measure_btn.clicked.connect(self.measure)
        self.clean_btn = _btn(tr("clean_selected"), "trash", danger=True)
        self.clean_btn.clicked.connect(self.clean)
        row.addWidget(self.measure_btn)
        row.addWidget(self.clean_btn)
        lay.addLayout(row)
        self.load()

    def load(self):
        try:
            self.locs = cleanup.known_locations()
        except Exception:
            self.locs = []
        if SCREENSHOT:
            demo = [5.1, 0.6, 2.4, 1.3, 0.2, 0.9, 3.1, 6.2, 0.4, 0.8, 1.7, 0.5, 0.3]
            for i, loc in enumerate(self.locs):
                loc.size = int(demo[i % len(demo)] * 1024 ** 3)
                loc.files = 1200 + 377 * i
        self.render()
        self.update_recycle()

    def update_recycle(self):
        size, n = (int(4.6 * 1024 ** 3), 318) if SCREENSHOT else cleanup.recycle_bin_info()
        if size < 0:
            self.rb_label.setText(tr("recycle_bin"))
        else:
            self.rb_label.setText(tr("recycle_info", size=human(size), n=_num(n)))

    def render(self):
        t = self.table
        t.setRowCount(len(self.locs))
        for i, loc in enumerate(self.locs):
            cb = QTableWidgetItem(tr(loc.key))
            cb.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            cb.setCheckState(Qt.Checked if loc.key in ("loc_user_temp", "loc_crashdumps", "loc_d3d") else Qt.Unchecked)
            cb.setToolTip("\n".join(loc.paths))
            t.setItem(i, 0, cb)
            self._set_size(i)
            t.setItem(i, 3, _item(tr(loc.note) if loc.note else ""))
        self._update_footer()

    def _set_size(self, i):
        loc = self.locs[i]
        if loc.size < 0:
            self.table.setItem(i, 1, _item(tr("not_measured"), None, True))
            self.table.setItem(i, 2, _item("", None, True))
        else:
            self.table.setItem(i, 1, _item(human(loc.size), loc.size, True))
            self.table.setItem(i, 2, _item(_num(loc.files), loc.files, True))

    def _update_footer(self):
        known = [l.size for l in self.locs if l.size >= 0]
        self.footer.setText(f"{tr('total')}: {human(sum(known))}" if known else "")

    def checked(self):
        out = []
        for i, loc in enumerate(self.locs):
            it = self.table.item(i, 0)
            if it is not None and it.checkState() == Qt.Checked:
                out.append(loc)
        return out

    def measure(self):
        if self.worker is not None:
            return
        for i in range(len(self.locs)):
            self.table.setItem(i, 1, _item(tr("measuring"), None, True))

        def job(progress, locs):
            res = []
            for k, loc in enumerate(locs):
                if progress.cancelled():
                    break
                total = files = 0
                for p in loc.paths:
                    s, f = cleanup.dir_size(p, progress.cancelled)
                    total += s
                    files += f
                res.append((total, files))
                progress(int(100 * (k + 1) / max(1, len(locs))), "")
            return res

        self.measure_btn.setEnabled(False)
        self.worker = Worker(job, self.locs)
        self.worker.signals.result.connect(self._measured)
        self.worker.signals.finished.connect(self._done)
        run_worker(self.worker)

    def _measured(self, res):
        for i, (s, f) in enumerate(res):
            if i < len(self.locs):
                self.locs[i].size, self.locs[i].files = s, f
        for i in range(len(self.locs)):
            self._set_size(i)
        self._update_footer()
        self.update_recycle()

    def _done(self):
        self.worker = None
        self.measure_btn.setEnabled(True)
        self.clean_btn.setEnabled(True)

    def clean(self):
        locs = self.checked()
        if not locs:
            info(self, tr("nothing_selected"))
            return
        lst = "\n".join(tr(l.key) for l in locs)
        if not ask(self, tr("confirm_clean", list=lst)):
            return
        exclude = [getattr(sys, "_MEIPASS", ""), os.path.join(os.environ.get("TEMP", ""), "BahtiyorSoft_ui")]

        def job(progress, locs):
            paths = []
            for loc in locs:
                for p in loc.paths:
                    paths += cleanup.contents(p, exclude)
            return cleanup.trash_paths(paths, progress=progress)

        self.clean_btn.setEnabled(False)
        self.measure_btn.setEnabled(False)
        self.worker = Worker(job, locs)
        self.worker.signals.result.connect(self._cleaned)
        self.worker.signals.error.connect(lambda m: error(self, m))
        self.worker.signals.finished.connect(self._done)
        run_worker(self.worker)

    def _cleaned(self, res):
        ok, failed = res
        msg = tr("trash_done", ok=_num(len(ok)), fail=_num(len(failed)))
        if failed:
            msg += "\n" + tr("trash_failed_hint")
        info(self, msg)
        self.measure()


# =========================================================================== Asosiy oyna
class MainWindow(BaseMainWindow):
    def __init__(self):
        super().__init__()
        self.result: ScanResult = None
        self.worker = None
        self._scan_total = 0
        self._t0 = 0.0

        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        # ---- asboblar paneli
        bar = QFrame()
        bar.setObjectName("TopBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(8)
        lbl = QLabel(tr("target"))
        lbl.setObjectName("Muted")
        bl.addWidget(lbl)
        self.target = QComboBox()
        self.target.setEditable(True)
        self.target.setMinimumWidth(260)
        self.target.lineEdit().setPlaceholderText(tr("target_ph"))
        self.target.lineEdit().returnPressed.connect(lambda: self.start_scan())
        bl.addWidget(self.target, 1)
        self.pick_btn = _tool("folder", tr("pick_folder"))
        self.pick_btn.clicked.connect(self.pick_folder)
        bl.addWidget(self.pick_btn)
        self.scan_btn = primary_button(tr("scan"))
        self.scan_btn.clicked.connect(lambda: self.start_scan())
        bl.addWidget(self.scan_btn)
        self.stop_btn = _btn(tr("stop"), "stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_scan)
        bl.addWidget(self.stop_btn)
        sep = QFrame()
        sep.setObjectName("VSep")
        sep.setFixedWidth(1)
        bl.addWidget(sep)
        self.export_btn = QToolButton()
        self.export_btn.setText(tr("export"))
        self.export_btn.setIcon(icon("export"))
        self.export_btn.setProperty("iconName", "export")
        self.export_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.export_btn.setPopupMode(QToolButton.InstantPopup)
        self.export_btn.setObjectName("ExportBtn")
        m = QMenu(self.export_btn)
        m.addAction(tr("export_html")).triggered.connect(lambda: self.export("html"))
        m.addAction(tr("export_csv")).triggered.connect(lambda: self.export("csv"))
        self.export_btn.setMenu(m)
        bl.addWidget(self.export_btn)
        rl.addWidget(bar)

        # ---- holat qatori
        st = QFrame()
        st.setObjectName("ScanStrip")
        sl = QHBoxLayout(st)
        sl.setContentsMargins(16, 6, 16, 6)
        sl.setSpacing(12)
        self.info_lbl = QLabel(tr("idle"))
        self.info_lbl.setObjectName("Muted")
        sl.addWidget(self.info_lbl, 1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(220)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        sl.addWidget(self.progress)
        rl.addWidget(st)

        # ---- varaqlar
        self.tabs = QTabWidget()
        self.tabs.setObjectName("MainTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(False)
        self.drives_page = DrivesPage(self)
        self.map_page = MapPage(self)
        self.folders_page = FoldersPage(self)
        self.largest_page = LargestPage(self)
        self.types_page = TypesPage(self)
        self.old_page = OldPage(self)
        self.clean_page = CleanPage(self)
        for page, key in ((self.drives_page, "tab_drives"), (self.map_page, "tab_map"),
                          (self.folders_page, "tab_folders"), (self.largest_page, "tab_largest"),
                          (self.types_page, "tab_types"), (self.old_page, "tab_old"),
                          (self.clean_page, "tab_clean")):
            self.tabs.addTab(page, tr(key))
        rl.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

        self._fill_targets()
        if SCREENSHOT:
            from .demo import demo_result
            self.target.setEditText("C:\\")
            self.apply_result(demo_result("C:\\"), switch=False)

    # ------------------------------------------------------------------ sahifalar (tekshiruv uchun)
    def page_count(self) -> int:
        return self.tabs.count()

    def set_page(self, i: int):
        if 0 <= i < self.tabs.count():
            self.tabs.setCurrentIndex(i)

    def on_theme_changed(self):
        from . import views
        views._icon_cache.clear()
        for cls in (QToolButton, QPushButton):
            for w in self.findChildren(cls):
                name = w.property("iconName")
                if name:
                    w.setIcon(icon(name))
        self.drives_page.reload()
        self.update()

    # ------------------------------------------------------------------ joy tanlash
    def _fill_targets(self):
        self.target.clear()
        for d in list_drives():
            self.target.addItem(icon("drive", current_colors()["muted"], 16), d.mount, d.mount)
        last = self.settings.get("last_target") if self.settings else None
        if last and not SCREENSHOT:
            self.target.setEditText(last)

    def pick_folder(self):
        start = self.target.currentText() or os.path.expanduser("~")
        p = QFileDialog.getExistingDirectory(self, tr("select_folder"), start)
        if p:
            self.target.setEditText(os.path.normpath(p))
            self.start_scan()

    # ------------------------------------------------------------------ skanerlash
    def start_scan(self, path: str = None):
        if self.worker is not None:
            self.status(tr("scan_busy"))
            return
        path = (path or self.target.currentText()).strip().strip('"')
        if len(path) == 2 and path[1] == ":":
            path += "\\"
        if not path or not os.path.isdir(path):
            error(self, tr("bad_path", path=path or "?"))
            return
        path = os.path.normpath(path)
        if path.endswith(":"):
            path += "\\"
        self.target.setEditText(path)
        if self.settings and not SCREENSHOT:
            self.settings.set("last_target", path)
        self._scan_total = 0
        try:
            import psutil
            if os.path.splitdrive(path)[1] in ("\\", "/"):
                self._scan_total = psutil.disk_usage(path).used
        except Exception:
            pass

        def job(progress, p):
            def cb(files, dirs, size, cur):
                pct = int(100 * size / self._scan_total) if self._scan_total else 0
                progress(min(pct, 99), f"{files}\t{size}\t{cur}")
            return run_scan(p, progress=cb, cancelled=progress.cancelled)

        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100 if self._scan_total else 0)
        self.progress.setValue(0)
        self.info_lbl.setText(tr("scanning", files=0, size=human(0)))
        self._t0 = time.time()
        self.worker = Worker(job, path)
        self.worker.signals.progress.connect(self._on_progress)
        self.worker.signals.result.connect(self.apply_result)
        self.worker.signals.error.connect(lambda m: error(self, m))
        self.worker.signals.finished.connect(self._scan_finished)
        run_worker(self.worker)

    def stop_scan(self):
        if self.worker is not None:
            self.worker.cancel()
            self.stop_btn.setEnabled(False)

    def _on_progress(self, pct, msg):
        try:
            files, size, cur = msg.split("\t", 2)
            files, size = int(files), int(size)
        except ValueError:
            return
        if self._scan_total:
            self.progress.setValue(pct)
        self.info_lbl.setText(tr("scanning", files=_num(files), size=human(size)))
        self.status(cur, 2000)

    def _scan_finished(self):
        self.worker = None
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)

    def apply_result(self, res: ScanResult, switch: bool = True):
        if res is None:
            return
        self.result = res
        root = res.root
        txt = tr("summary", path=root.path, size=human(root.size), files=_num(root.file_count),
                 dirs=_num(root.dir_count), sec=f"{res.seconds:.1f}")
        if res.errors:
            txt += "   " + tr("summary_err", n=_num(res.errors))
        if res.cancelled:
            txt += "   " + tr("cancelled")
        self.info_lbl.setText(txt)
        self.map_page.set_node(root)
        self.map_page.set_legend(res)
        self.folders_page.set_result(res)
        self.largest_page.set_result(res)
        self.types_page.set_result(res)
        self.old_page.set_result(res)
        if switch:
            self.tabs.setCurrentWidget(self.map_page)

    def show_on_map(self, node: DirNode):
        self.map_page.set_node(node)
        self.tabs.setCurrentWidget(self.map_page)

    # ------------------------------------------------------------------ Savatga
    def trash(self, items) -> bool:
        """items: [(path, size)]. Tasdiqdan so'ng faqat Savatga yuboradi."""
        items = [(p, s) for p, s in items if p]
        if not items:
            return False
        prot = [p for p, _ in items if cleanup.is_protected(p)]
        if prot:
            error(self, tr("protected") + "\n\n" + "\n".join(prot[:5]))
            return False
        lst = "\n".join(p for p, _ in items[:8])
        if len(items) > 8:
            lst += "\n" + tr("and_more", n=len(items) - 8)
        total = sum(s or 0 for _, s in items)
        if not ask(self, tr("confirm_trash", n=len(items), size=human(total), list=lst)):
            return False
        ok, failed = cleanup.trash_paths([p for p, _ in items])
        msg = tr("trash_done", ok=len(ok), fail=len(failed))
        if failed:
            msg += "\n\n" + "\n".join(f"{p}: {e}" for p, e in failed[:5])
        msg += "\n" + tr("rescan_hint")
        info(self, msg)
        return bool(ok)

    # ------------------------------------------------------------------ hisobot
    def export(self, kind: str):
        if self.result is None:
            info(self, tr("need_scan"))
            return
        flt = "HTML (*.html)" if kind == "html" else "CSV (*.csv)"
        start = os.path.join(os.path.expanduser("~"), "Documents", default_name(self.result, kind))
        p, _ = QFileDialog.getSaveFileName(self, tr("export"), start, flt)
        if not p:
            return
        try:
            if kind == "html":
                export_html(self.result, p, tr, appmod.META.get("accent", "#d89b1c"))
            else:
                export_csv(self.result, p, tr)
        except OSError as ex:
            error(self, str(ex))
            return
        self.status(tr("saved_to", path=p))
        if kind == "html":
            open_path(p)

    def closeEvent(self, e):
        if self.worker is not None:
            self.worker.cancel()
        super().closeEvent(e)
