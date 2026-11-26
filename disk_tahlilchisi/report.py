"""Hisobot eksporti: CSV va HTML."""
import csv
import html
import os
from datetime import datetime
from typing import Callable

from .filetypes import by_category, color
from .scanner import ScanResult


def human(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _date(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OSError, ValueError, OverflowError):
        return ""


def _top_folders(res: ScanResult, limit: int = 30):
    root = res.root
    total = root.size or 1
    return [(c.path, c.size, 100.0 * c.size / total, c.file_count) for c in root.children[:limit]]


def export_csv(res: ScanResult, path: str, tr: Callable[[str], str] = lambda k: k) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([tr("rep_title"), res.root.path, human(res.total_size), res.total_files])
        w.writerow([])
        w.writerow([tr("col_folder"), tr("col_size_bytes"), tr("col_percent"), tr("col_files")])
        for p, sz, pct, cnt in _top_folders(res, 1000):
            w.writerow([p, sz, f"{pct:.1f}", cnt])
        w.writerow([])
        w.writerow([tr("col_file"), tr("col_size_bytes"), tr("col_modified")])
        for sz, p, mt, _at in res.top_files:
            w.writerow([p, sz, _date(mt)])
        w.writerow([])
        w.writerow([tr("col_ext"), tr("col_size_bytes"), tr("col_files")])
        for e, (sz, cnt) in sorted(res.ext_stats.items(), key=lambda kv: kv[1][0], reverse=True):
            w.writerow([e, sz, cnt])


def export_html(res: ScanResult, path: str, tr: Callable[[str], str] = lambda k: k, accent: str = "#d89b1c") -> None:
    e = html.escape
    total = res.total_size or 1
    rows_f = "".join(
        f"<tr><td>{e(p)}</td><td class=n>{human(sz)}</td><td><div class=bar><i style='width:{pct:.1f}%'></i></div>"
        f"</td><td class=n>{pct:.1f}%</td><td class=n>{_num(cnt)}</td></tr>"
        for p, sz, pct, cnt in _top_folders(res, 50))
    rows_l = "".join(f"<tr><td>{e(p)}</td><td class=n>{human(sz)}</td><td class=n>{_date(mt)}</td></tr>"
                     for sz, p, mt, _ in res.top_files)
    rows_c = "".join(
        f"<tr><td><span class=dot style='background:{color(c)}'></span>{e(tr('cat_' + c))}</td>"
        f"<td class=n>{human(sz)}</td><td><div class=bar><i style='width:{100 * sz / total:.1f}%;"
        f"background:{color(c)}'></i></div></td><td class=n>{cnt}</td></tr>"
        for c, (sz, cnt) in by_category(res.ext_stats).items())
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(tr('rep_title'))}</title>
<style>
body{{font-family:"Segoe UI",Arial,sans-serif;margin:32px;color:#222;background:#fafaf8}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px;border-bottom:2px solid {accent};
padding-bottom:4px}} .meta{{color:#666}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{padding:5px 8px;border-bottom:1px solid #e5e3dd;text-align:left}} th{{background:#f0eee9}}
.n{{text-align:right;white-space:nowrap}} .bar{{background:#eee;height:8px;width:160px;border-radius:2px}}
.bar i{{display:block;height:8px;background:{accent};border-radius:2px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}}
</style></head><body>
<h1>{e(tr('rep_title'))}</h1>
<div class=meta>{e(res.root.path)} &middot; {human(res.total_size)} &middot; {_num(res.total_files)} {e(tr('rep_files'))}
&middot; {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
<h2>{e(tr('tab_folders'))}</h2><table><tr><th>{e(tr('col_folder'))}</th><th>{e(tr('col_size'))}</th><th></th>
<th>%</th><th>{e(tr('col_files'))}</th></tr>{rows_f}</table>
<h2>{e(tr('tab_types'))}</h2><table><tr><th>{e(tr('col_type'))}</th><th>{e(tr('col_size'))}</th><th></th>
<th>{e(tr('col_files'))}</th></tr>{rows_c}</table>
<h2>{e(tr('tab_largest'))}</h2><table><tr><th>{e(tr('col_file'))}</th><th>{e(tr('col_size'))}</th>
<th>{e(tr('col_modified'))}</th></tr>{rows_l}</table>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return None


def default_name(res: ScanResult, ext: str) -> str:
    base = os.path.basename(res.root.path.rstrip("\\/")) or res.root.path[:1]
    return f"disk_{base}_{datetime.now():%Y%m%d}.{ext}"
