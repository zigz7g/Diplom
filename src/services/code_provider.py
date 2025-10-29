# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path, PurePosixPath, PurePath
from typing import Optional, Dict, List

def _norm_rel(s: str) -> str:
    if not s:
        return ""
    # приводим к posix, без ведущего слеша и диска
    p = str(PurePosixPath(s)).lstrip("/")
    # иногда прилетает "/C:/...": убираем ведущий "/"
    if len(p) >= 3 and p[1] == ":":
        p = p[2:].lstrip("/")
    return p.lower()

def _tails(parts: List[str], upto: int = 4) -> List[str]:
    res = []
    n = len(parts)
    for k in range(1, min(upto, n) + 1):
        res.append("/".join(parts[-k:]).lower())
    return res

class CodeProvider:
    """
    Хранит индекс файлов проекта и умеет по строке из SARIF (uri, относительный путь,
    или хвост пути) найти файл на диске.
    """
    def __init__(self, root: Optional[Path]):
        self.root: Optional[Path] = None
        self._by_rel: Dict[str, Path] = {}
        self._by_tail: Dict[str, Path] = {}
        self._by_name: Dict[str, List[Path]] = {}
        if root:
            self.set_root(root)

    def set_root(self, root: Path) -> None:
        self.root = Path(root)
        self._by_rel.clear(); self._by_tail.clear(); self._by_name.clear()
        if not self.root.exists():
            return
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            rel = _norm_rel(str(p.relative_to(self.root)))
            if rel:
                self._by_rel[rel] = p
                # хвосты до 4 сегментов
                parts = rel.split("/")
                for t in _tails(parts, 4):
                    self._by_tail.setdefault(t, p)
            name = p.name.lower()
            self._by_name.setdefault(name, []).append(p)

    def find(self, hint: str) -> Optional[Path]:
        """
        hint может быть: абсолютный путь; uri вида file:///...; относительный; хвост пути; просто имя.
        """
        if not hint:
            return None

        # абсолютный путь
        p = Path(hint)
        if p.is_absolute() and p.exists():
            return p

        if not self.root or not self.root.exists():
            return None

        # file:/// URI и posix → относительный
        rel = _norm_rel(hint)

        # 1) прямой join(root / rel)
        p2 = self.root.joinpath(*PurePosixPath(rel).parts)
        if p2.exists():
            return p2

        # 2) точное совпадение по нормализованному относительному
        hit = self._by_rel.get(rel)
        if hit and hit.exists():
            return hit

        # 3) хвост пути (чем длиннее, тем лучше)
        parts = rel.split("/")
        for t in reversed(_tails(parts, 4)):
            hit = self._by_tail.get(t)
            if hit and hit.exists():
                return hit

        # 4) по имени файла
        cand = self._by_name.get(Path(rel).name.lower())
        if cand:
            for c in cand:
                if c.exists():
                    return c

        return None
