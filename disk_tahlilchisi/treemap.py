"""Squarified treemap algoritmi (Bruls, Huizing, van Wijk, 2000). Qt'ga bog'liq emas."""
from typing import List, Sequence, Tuple

Rect = Tuple[float, float, float, float]   # x, y, w, h


def _worst(row: Sequence[float], side: float) -> float:
    s = sum(row)
    if s <= 0 or side <= 0:
        return float("inf")
    mx, mn = max(row), min(row)
    s2, w2 = s * s, side * side
    return max(w2 * mx / s2, s2 / (w2 * mn)) if mn > 0 else float("inf")


def squarify(values: Sequence[float], x: float, y: float, w: float, h: float) -> List[Rect]:
    """values (kamayish tartibida bo'lishi shart emas) uchun to'rtburchaklar.

    Natija values bilan bir xil tartibda qaytadi. Nol/manfiy qiymatlar uchun (x, y, 0, 0).
    """
    n = len(values)
    out: List[Rect] = [(x, y, 0.0, 0.0)] * n
    total = float(sum(v for v in values if v > 0))
    if total <= 0 or w <= 0 or h <= 0:
        return out
    order = sorted((i for i in range(n) if values[i] > 0), key=lambda i: values[i], reverse=True)
    scale = w * h / total
    areas = [values[i] * scale for i in order]

    cx, cy, cw, ch = x, y, w, h
    i = 0
    while i < len(areas):
        side = min(cw, ch)
        row = [areas[i]]
        j = i + 1
        while j < len(areas) and _worst(row + [areas[j]], side) <= _worst(row, side):
            row.append(areas[j])
            j += 1
        s = sum(row)
        if cw >= ch:            # chap tomonga ustun
            colw = s / ch if ch else 0
            yy = cy
            for k, a in enumerate(row):
                hh = a / colw if colw else 0
                out[order[i + k]] = (cx, yy, colw, hh)
                yy += hh
            cx += colw
            cw -= colw
        else:                   # yuqoriga qator
            rowh = s / cw if cw else 0
            xx = cx
            for k, a in enumerate(row):
                ww = a / rowh if rowh else 0
                out[order[i + k]] = (xx, cy, ww, rowh)
                xx += ww
            cy += rowh
            ch -= rowh
        i = j
    return out
