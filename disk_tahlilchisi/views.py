"""Chizma vidjetlar: belgilar, band joy chizig'i, treemap, toifalar diagrammasi, ulush ustuni."""
import os
from typing import List, Optional

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPen,
                           QPixmap)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolTip,
                               QWidget)

from uzkit.i18n import tr
from uzkit.paths import resource
from uzkit.theme import colors

from .filetypes import category, color as cat_color
from .report import human
from .scanner import DirNode
from .treemap import squarify


# --------------------------------------------------------------------------- belgilar
_icon_cache = {}


def icon(name: str, col: str = None, size: int = 20) -> QIcon:
    """assets/icons/<name>.svg ni berilgan rangda QIcon qiladi."""
    col = col or current_colors()["text"]
    key = (name, col, size)
    if key in _icon_cache:
        return _icon_cache[key]
    ic = QIcon()
    p = resource("assets", "icons", f"{name}.svg")
    if p.exists():
        svg = p.read_text(encoding="utf-8").replace("COLOR", col)
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        for s in (size, size * 2):
            pm = QPixmap(s, s)
            pm.fill(Qt.transparent)
            pa = QPainter(pm)
            r.render(pa)
            pa.end()
            ic.addPixmap(pm)
    _icon_cache[key] = ic
    return ic


def _mode_colors():
    from uzkit import app as appmod
    mode = "system"
    try:
        mode = appmod.SETTINGS.get("theme", "system") if appmod.SETTINGS else "system"
    except Exception:
        pass
    import sys
    if "--theme" in sys.argv:
        i = sys.argv.index("--theme")
        if i + 1 < len(sys.argv):
            mode = sys.argv[i + 1]
    return colors(mode)


def current_colors() -> dict:
    """Ilova palitrasidan joriy ranglar (mavzu almashganda ham to'g'ri)."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    c = _mode_colors()
    app = QApplication.instance()
    if app is not None:
        pal = app.palette()
        c["bg"] = pal.color(QPalette.Window).name()
        c["surface"] = pal.color(QPalette.Base).name()
        c["surface2"] = pal.color(QPalette.AlternateBase).name()
        c["text"] = pal.color(QPalette.Text).name()
        c["muted"] = pal.color(QPalette.PlaceholderText).name()
    return c


def is_dark() -> bool:
    return QColor(current_colors()["bg"]).lightnessF() < 0.5


def usage_color(pct: float, accent: str) -> str:
    if pct >= 92:
        return "#d0453a"
    if pct >= 80:
        return "#e0892b"
    return accent


# --------------------------------------------------------------------------- band joy chizig'i
class UsageBar(QWidget):
    def __init__(self, pct: float = 0.0, parent=None):
        super().__init__(parent)
        self.pct = pct
        self.setFixedHeight(10)

    def set_percent(self, pct: float):
        self.pct = pct
        self.update()

    def paintEvent(self, e):
        c = current_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["surface2"]) if not is_dark() else QColor(c["bg"]))
        p.drawRoundedRect(r, 3, 3)
        w = r.width() * max(0.0, min(100.0, self.pct)) / 100
        if w > 0:
            p.setBrush(QColor(usage_color(self.pct, c.get("accent", "#d89b1c"))))
            p.drawRoundedRect(QRectF(r.x(), r.y(), max(w, 4), r.height()), 3, 3)
        p.end()


# --------------------------------------------------------------------------- ulush ustuni (jadval)
class ShareDelegate(QStyledItemDelegate):
    """Qiymat: 0..100 (Qt.UserRole + 1). Kichik chiziq va foiz matni chiziladi."""
    ROLE = Qt.UserRole + 1

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        pct = index.data(self.ROLE)
        if pct is None:
            return
        c = current_colors()
        sel = bool(opt.state & QStyle.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(6, 0, -6, 0)
        fm = QFontMetrics(option.font)
        tw = fm.horizontalAdvance("100.0%") + 6
        bar = QRectF(r.x(), r.center().y() - 3.5, max(10.0, r.width() - tw), 7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 60) if sel else (QColor(c["muted"]).lighter(165) if not is_dark()
                                                               else QColor(c["bg"])))
        painter.drawRoundedRect(bar, 2, 2)
        painter.setBrush(QColor("#ffffff") if sel else QColor(c.get("accent", "#d89b1c")))
        painter.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * min(100.0, pct) / 100, bar.height()), 2, 2)
        painter.setPen(QColor("#ffffff") if sel else QColor(c["text"]))
        painter.drawText(QRectF(bar.right() + 4, r.y(), tw - 4, r.height()), Qt.AlignVCenter | Qt.AlignRight,
                         f"{pct:.1f}%")
        painter.restore()


# --------------------------------------------------------------------------- treemap
class _Cell:
    __slots__ = ("rect", "kind", "obj", "name", "size", "depth", "color", "path")

    def __init__(self, rect, kind, obj, name, size, depth, color, path):
        self.rect, self.kind, self.obj, self.name = rect, kind, obj, name
        self.size, self.depth, self.color, self.path = size, depth, color, path


class TreemapView(QWidget):
    """Papka tarkibini squarified treemap ko'rinishida chizadi. Papka bosilsa — open_dir(DirNode)."""
    open_dir = Signal(object)
    hovered = Signal(str)
    context = Signal(object, object)      # (_Cell, QPoint global)

    HEADER = 18

    def __init__(self, parent=None):
        super().__init__(parent)
        self.node: Optional[DirNode] = None
        self.cells: List[_Cell] = []
        self._hover: Optional[_Cell] = None
        self.setMouseTracking(True)
        self.setMinimumSize(300, 200)

    def set_node(self, node: Optional[DirNode]):
        self.node = node
        self._hover = None
        self._layout()
        self.update()

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    # ---------------------------------------------------------------- joylashtirish
    def _items(self, node: DirNode):
        items = [("dir", c, c.name, c.size) for c in node.children if c.size > 0]
        items += [("file", f, f[0], f[1]) for f in node.files if f[1] > 0]
        if node.rest_size > 0:
            items.append(("rest", node, tr("small_files", n=node.rest_count), node.rest_size))
        return items

    def _place(self, node: DirNode, rect: QRectF, depth: int):
        items = self._items(node)
        if not items:
            return
        rects = squarify([it[3] for it in items], rect.x(), rect.y(), rect.width(), rect.height())
        for (kind, obj, name, size), (x, y, w, h) in zip(items, rects):
            if w < 1 or h < 1:
                continue
            r = QRectF(x, y, w, h)
            if kind == "file":
                col = cat_color(category(name))
                path = os.path.join(node.path, name)
            elif kind == "rest":
                col = "#8a8f98"
                path = node.path
            else:
                col = None
                path = obj.path
            cell = _Cell(r, kind, obj, name, size, depth, col, path)
            self.cells.append(cell)
            if kind == "dir" and depth < 6 and w > 40 and h > 36:
                inner = r.adjusted(2, self.HEADER, -2, -2)
                if inner.width() > 8 and inner.height() > 8:
                    self._place(obj, inner, depth + 1)

    def _layout(self):
        self.cells = []
        if self.node is None or self.node.size <= 0:
            return
        self._place(self.node, QRectF(self.rect()).adjusted(1, 1, -1, -1), 0)

    # ---------------------------------------------------------------- chizish
    def paintEvent(self, e):
        c = current_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QColor(c["surface"]))
        if not self.cells:
            p.setPen(QColor(c["muted"]))
            p.drawText(self.rect().adjusted(40, 0, -40, 0), Qt.AlignCenter | Qt.TextWordWrap, tr("map_empty"))
            p.end()
            return
        dark = is_dark()
        dir_fill = [QColor("#2b3036") if dark else QColor("#e4e1d9"),
                    QColor("#343a41") if dark else QColor("#d8d4ca"),
                    QColor("#3d444c") if dark else QColor("#cdc8bc"),
                    QColor("#454d56") if dark else QColor("#c3bdb0")]
        edge = QColor(c["surface"])
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = QFontMetrics(f)
        for cell in self.cells:
            r = cell.rect
            if cell.kind == "dir":
                base = dir_fill[min(cell.depth, 3)]
                p.fillRect(r, base)
                p.setPen(QPen(edge, 1))
                p.drawRect(r.adjusted(0, 0, -1, -1))
                if r.height() > 14 and r.width() > 30:
                    p.setPen(QColor(c["text"]))
                    label = fm.elidedText(f"{cell.name}  {human(cell.size)}", Qt.ElideRight, int(r.width() - 8))
                    p.drawText(QRectF(r.x() + 4, r.y(), r.width() - 8, self.HEADER), Qt.AlignVCenter | Qt.AlignLeft,
                               label)
            else:
                col = QColor(cell.color)
                g = QLinearGradient(r.topLeft(), r.bottomRight())
                g.setColorAt(0, col.lighter(118))
                g.setColorAt(1, col.darker(118))
                p.fillRect(r, QBrush(g))
                p.setPen(QPen(edge, 1))
                p.drawRect(r.adjusted(0, 0, -1, -1))
                if r.width() > 60 and r.height() > 30:
                    p.setPen(QColor("#ffffff"))
                    name = fm.elidedText(cell.name, Qt.ElideMiddle, int(r.width() - 8))
                    p.drawText(QRectF(r.x() + 4, r.y() + 3, r.width() - 8, 16), Qt.AlignLeft | Qt.AlignVCenter, name)
                    p.drawText(QRectF(r.x() + 4, r.y() + 18, r.width() - 8, 16), Qt.AlignLeft | Qt.AlignVCenter,
                               human(cell.size))
        if self._hover is not None:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor(c.get("accent", "#d89b1c")), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self._hover.rect.adjusted(1, 1, -1, -1))
        p.end()

    # ---------------------------------------------------------------- sichqoncha
    def cell_at(self, pos) -> Optional[_Cell]:
        found = None
        for cell in self.cells:      # ichki (chuqurroq) kataklar keyin keladi
            if cell.rect.contains(QPointF(pos)):
                found = cell
        return found

    def _dir_target(self, cell: _Cell) -> Optional[DirNode]:
        """Bosilgan joyga mos, joriy papkaning bevosita ichidagi papka."""
        if cell is None:
            return None
        node = cell.obj if cell.kind == "dir" else None
        if node is None:
            # fayl yoki mayda fayllar — ularning papkasi
            for c2 in reversed(self.cells):
                if c2.kind == "dir" and c2.rect.contains(cell.rect.center()):
                    node = c2.obj
                    break
        if node is None:
            return None
        while node.parent is not None and node.parent is not self.node:
            node = node.parent
        return node if node.parent is self.node else None

    def mouseMoveEvent(self, e):
        cell = self.cell_at(e.position())
        if cell is not self._hover:
            self._hover = cell
            self.update()
        if cell is not None:
            pct = 100.0 * cell.size / max(1, self.node.size)
            text = f"{cell.path}\n{human(cell.size)}  ({pct:.1f}%)"
            if cell.kind == "dir":
                text += f"\n{tr('col_files')}: {cell.obj.file_count}"
            QToolTip.showText(e.globalPosition().toPoint(), text, self)
            self.hovered.emit(cell.path)

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def mouseReleaseEvent(self, e):
        cell = self.cell_at(e.position())
        if e.button() == Qt.LeftButton:
            target = self._dir_target(cell)
            if target is not None:
                self.open_dir.emit(target)
        elif e.button() == Qt.RightButton and cell is not None:
            self.context.emit(cell, e.globalPosition().toPoint())

    def sizeHint(self):
        return QSize(700, 450)


# --------------------------------------------------------------------------- toifalar diagrammasi
class CategoryChart(QWidget):
    """Gorizontal ustunlar: toifa nomi, chiziq, hajm."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []      # (label, size, color, count)
        self.setMinimumHeight(120)

    def set_rows(self, rows):
        self.rows = rows
        self.setMinimumHeight(max(120, 28 * len(rows) + 8))
        self.update()

    def paintEvent(self, e):
        c = current_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.rows:
            p.setPen(QColor(c["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, tr("need_scan"))
            p.end()
            return
        fm = QFontMetrics(self.font())
        lw = max(fm.horizontalAdvance(r[0]) for r in self.rows) + 26
        sw = fm.horizontalAdvance("999.9 GB") + 12
        mx = max(r[1] for r in self.rows) or 1
        total = sum(r[1] for r in self.rows) or 1
        y = 4
        for label, size, col, _cnt in self.rows:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(0, y + 7, 10, 10), 2, 2)
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(18, y, lw, 24), Qt.AlignVCenter | Qt.AlignLeft, label)
            bw = max(0.0, self.width() - lw - sw - 70)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(lw + 4, y + 6, max(2.0, bw * size / mx), 12), 2, 2)
            p.setPen(QColor(c["text"]))
            p.drawText(QRectF(self.width() - sw - 64, y, sw, 24), Qt.AlignVCenter | Qt.AlignRight, human(size))
            p.setPen(QColor(c["muted"]))
            p.drawText(QRectF(self.width() - 58, y, 56, 24), Qt.AlignVCenter | Qt.AlignRight,
                       f"{100 * size / total:.1f}%")
            y += 28
        p.end()
