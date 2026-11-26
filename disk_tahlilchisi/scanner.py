"""Ko'p oqimli papka skaneri.

Ish tartibi: navbat (queue) dagi har bir papka bitta oqimda os.scandir bilan o'qiladi, ichki papkalar
navbatga qo'shiladi. Hammasi tugagach, o'lchamlar pastdan yuqoriga yig'iladi.
Reparse point (junction, symlink) larga kirilmaydi, ruxsat berilmagan papkalar sanab boriladi.
"""
import heapq
import os
import queue
import stat
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .filetypes import ext_of

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
FILES_PER_DIR = 40          # har bir papkada alohida saqlanadigan eng katta fayllar soni
TOP_FILES = 100
OLD_MIN_SIZE = 10 * 1024 * 1024


class FileRec(tuple):
    """(name, size, mtime, atime) — xotirani tejash uchun oddiy kortej."""
    __slots__ = ()

    def __new__(cls, name, size, mtime, atime):
        return tuple.__new__(cls, (name, size, mtime, atime))

    name = property(lambda s: s[0])
    size = property(lambda s: s[1])
    mtime = property(lambda s: s[2])
    atime = property(lambda s: s[3])


class DirNode:
    __slots__ = ("name", "parent", "children", "files", "rest_size", "rest_count",
                 "size", "file_count", "dir_count", "own_size", "own_count", "mtime", "error")

    def __init__(self, name: str, parent: "DirNode" = None):
        self.name = name
        self.parent = parent
        self.children: List[DirNode] = []
        self.files: List[FileRec] = []      # eng katta FILES_PER_DIR ta fayl
        self.rest_size = 0                  # qolgan (mayda) fayllar yig'indisi
        self.rest_count = 0
        self.own_size = 0                   # shu papkaning o'z fayllari
        self.own_count = 0
        self.size = 0                       # ichidagi hammasi bilan
        self.file_count = 0
        self.dir_count = 0
        self.mtime = 0.0
        self.error = False

    @property
    def path(self) -> str:
        parts = []
        n = self
        while n is not None:
            parts.append(n.name)
            n = n.parent
        parts.reverse()
        root = parts[0]
        return os.path.join(root, *parts[1:]) if len(parts) > 1 else root

    def find(self, path: str) -> Optional["DirNode"]:
        """To'liq yo'l bo'yicha ichki papkani topadi."""
        base = os.path.normcase(os.path.normpath(self.path))
        target = os.path.normcase(os.path.normpath(path))
        if target == base:
            return self
        if not target.startswith(base.rstrip("\\/") + os.sep):
            return None
        rel = target[len(base.rstrip("\\/")) + 1:]
        node = self
        for part in rel.split(os.sep):
            nxt = next((c for c in node.children if os.path.normcase(c.name) == part), None)
            if nxt is None:
                return None
            node = nxt
        return node


@dataclass
class ScanResult:
    root: DirNode
    top_files: List[Tuple[int, str, float, float]]        # (size, path, mtime, atime), kattadan kichikka
    ext_stats: Dict[str, List[int]]                         # ext -> [size, count]
    old_candidates: List[Tuple[int, str, float, float]]   # >= OLD_MIN_SIZE
    errors: int = 0
    skipped_links: int = 0
    seconds: float = 0.0
    cancelled: bool = False
    error_paths: List[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return self.root.size

    @property
    def total_files(self) -> int:
        return self.root.file_count


class Scanner:
    """scan(path) — bloklaydigan chaqiruv; progress(files, dirs, bytes, current_path) vaqti-vaqti bilan."""

    def __init__(self, threads: int = 0, progress: Callable = None, cancelled: Callable[[], bool] = None):
        self.threads = threads or min(16, (os.cpu_count() or 4) * 2)
        self.progress = progress
        self.cancelled = cancelled or (lambda: False)
        self._lock = threading.Lock()
        self._files = 0
        self._dirs = 0
        self._bytes = 0
        self._errors = 0
        self._links = 0
        self._error_paths: List[str] = []
        self._top: list = []
        self._ext: Dict[str, List[int]] = {}
        self._old: list = []
        self._current = ""

    # ------------------------------------------------------------------ bitta papka
    def _scan_one(self, node: DirNode, path: str, q: "queue.Queue"):
        files: list = []
        local_ext: Dict[str, List[int]] = {}
        local_old = []
        subdirs = []
        try:
            with os.scandir(path) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs = getattr(st, "st_file_attributes", 0)
                    if attrs & REPARSE or e.is_symlink():
                        with self._lock:
                            self._links += 1
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        subdirs.append((e.name, e.path, st.st_mtime))
                    else:
                        sz = st.st_size
                        rec = FileRec(e.name, sz, st.st_mtime, st.st_atime)
                        files.append(rec)
                        x = ext_of(e.name)
                        s = local_ext.get(x)
                        if s is None:
                            local_ext[x] = [sz, 1]
                        else:
                            s[0] += sz
                            s[1] += 1
                        if sz >= OLD_MIN_SIZE:
                            local_old.append((sz, e.path, st.st_mtime, st.st_atime))
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
            node.error = True
            with self._lock:
                self._errors += 1
                if len(self._error_paths) < 200:
                    self._error_paths.append(path)
            return

        own = sum(f[1] for f in files)
        node.own_size = own
        node.own_count = len(files)
        if len(files) > FILES_PER_DIR:
            files.sort(key=lambda f: f[1], reverse=True)
            rest = files[FILES_PER_DIR:]
            node.rest_size = sum(f[1] for f in rest)
            node.rest_count = len(rest)
            files = files[:FILES_PER_DIR]
        node.files = files
        for name, p, mt in subdirs:
            child = DirNode(name, node)
            child.mtime = mt
            node.children.append(child)
            q.put((child, p))

        with self._lock:
            self._files += node.own_count
            self._dirs += 1
            self._bytes += own
            self._current = path
            for x, (sz, cnt) in local_ext.items():
                s = self._ext.get(x)
                if s is None:
                    self._ext[x] = [sz, cnt]
                else:
                    s[0] += sz
                    s[1] += cnt
            self._old.extend(local_old)
            # eng katta fayllar: kichik-uyum (min-heap) TOP_FILES ta
            for f in files:
                item = (f[1], os.path.join(path, f[0]), f[2], f[3])
                if len(self._top) < TOP_FILES:
                    heapq.heappush(self._top, item)
                elif item[0] > self._top[0][0]:
                    heapq.heapreplace(self._top, item)

    # ------------------------------------------------------------------ asosiy
    def scan(self, path: str) -> ScanResult:
        t0 = time.time()
        path = os.path.abspath(path)
        root = DirNode(path)
        try:
            root.mtime = os.stat(path).st_mtime
        except OSError:
            pass
        q: queue.Queue = queue.Queue()
        q.put((root, path))
        stop = threading.Event()

        def worker():
            while True:
                item = q.get()
                if item is None:
                    q.task_done()
                    return
                try:
                    if not self.cancelled():
                        self._scan_one(item[0], item[1], q)
                except Exception:
                    item[0].error = True
                finally:
                    q.task_done()

        threads = [threading.Thread(target=worker, daemon=True) for _ in range(self.threads)]
        for t in threads:
            t.start()

        def reporter():
            while not stop.wait(0.25):
                if self.progress:
                    with self._lock:
                        args = (self._files, self._dirs, self._bytes, self._current)
                    try:
                        self.progress(*args)
                    except Exception:
                        pass

        rt = threading.Thread(target=reporter, daemon=True)
        rt.start()
        q.join()
        for _ in threads:
            q.put(None)
        for t in threads:
            t.join(timeout=2)
        stop.set()
        rt.join(timeout=1)
        aggregate(root)
        top = sorted(self._top, key=lambda x: x[0], reverse=True)
        old = sorted(self._old, key=lambda x: x[0], reverse=True)
        return ScanResult(root=root, top_files=top, ext_stats=self._ext, old_candidates=old,
                          errors=self._errors, skipped_links=self._links, seconds=time.time() - t0,
                          cancelled=self.cancelled(), error_paths=list(self._error_paths))


def aggregate(root: DirNode) -> None:
    """O'lcham va sonlarni pastdan yuqoriga yig'adi (rekursiyasiz)."""
    order = []
    stack = [root]
    while stack:
        n = stack.pop()
        order.append(n)
        stack.extend(n.children)
    for n in reversed(order):
        n.size = n.own_size + sum(c.size for c in n.children)
        n.file_count = n.own_count + sum(c.file_count for c in n.children)
        n.dir_count = len(n.children) + sum(c.dir_count for c in n.children)
        n.children.sort(key=lambda c: c.size, reverse=True)
        n.files.sort(key=lambda f: f[1], reverse=True)


def scan(path: str, threads: int = 0, progress=None, cancelled=None) -> ScanResult:
    return Scanner(threads, progress, cancelled).scan(path)


def old_files(candidates, min_size: int, days: int, by: str = "atime", now: float = None):
    """Katta va uzoq vaqt ochilmagan/o'zgartirilmagan fayllar."""
    now = now or time.time()
    limit = now - days * 86400
    idx = 3 if by == "atime" else 2
    return [c for c in candidates if c[0] >= min_size and c[idx] < limit]
