# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional


def _read_text_best_effort(p: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "windows-1251", "utf-16", "utf-32", "iso-8859-1"):
        try:
            return p.read_text(encoding=enc)
        except Exception:
            pass
    return p.read_bytes().decode("utf-8", errors="replace")


class CodeProvider:
    """
    Индексация исходников и «умный» поиск файла:
      - точное совпадение относительного пути;
      - если в SARIF только имя (например, django.po) — берём все кандидаты и
        выбираем тот, где лучше совпадает сниппет/валидна линия.
    """
    def __init__(self, root: Optional[Path]):
        self.root: Optional[Path] = Path(root) if root else None
        self._by_rel: Dict[str, Path] = {}
        self._by_name: Dict[str, List[Path]] = {}

    def set_root(self, root: Path) -> None:
        self.root = Path(root)
        self._reindex()

    # -------- public API --------
    def read_text(self, p: Path) -> str:
        return _read_text_best_effort(p)

    def find(self, relpath_or_name: str) -> Optional[Path]:
        """
        Простой поиск: сначала по относительному пути, потом по имени.
        """
        if not self.root or not relpath_or_name:
            return None
        key = relpath_or_name.replace("\\", "/").lstrip("./").lower()
        if key in self._by_rel:
            return self._by_rel[key]
        base = os.path.basename(key).lower()
        cand = self._by_name.get(base, [])
        return cand[0] if cand else None

    def find_best(self, file_hint: str, line: int, snippet: str) -> Optional[Path]:
        """
        Лучший кандидат среди одноимённых файлов.
        Критерии:
          +2 — линия существует в файле,
          +len(needle) — найден фрагмент сниппета.
        """
        if not self.root:
            return None

        # 1) точное совпадение относительного пути
        key = (file_hint or "").replace("\\", "/").lstrip("./").lower()
        if key in self._by_rel:
            return self._by_rel[key]

        # 2) поиск по имени
        base = os.path.basename(key) if key else ""
        candidates = self._by_name.get(base.lower(), []) if base else []
        if not candidates:
            return None
        if len(candidates) == 1 and candidates[0].exists():
            return candidates[0]

        # 3) скоринг по линии и сниппету
        needles = self._needles_from_snippet(snippet)
        best, best_score = None, -1
        for p in candidates:
            try:
                text = _read_text_best_effort(p)
            except Exception:
                continue

            score = 0
            if line and 1 <= line <= (text.count("\n") + 1):
                score += 2
            for nd in needles:
                idx = text.find(nd)
                if idx != -1:
                    score += len(nd)
                    break

            if score > best_score:
                best, best_score = p, score

        return best or candidates[0]

    # -------- internals --------
    def _reindex(self) -> None:
        self._by_rel.clear()
        self._by_name.clear()
        if not self.root:
            return

        skip = {"venv", ".venv", ".git", ".idea", "__pycache__", "node_modules", "dist", "build"}
        for dirpath, dirnames, filenames in os.walk(self.root):
            dn = os.path.basename(dirpath)
            if dn in skip:
                dirnames[:] = []  # не спускаемся
                continue
            for fn in filenames:
                p = Path(dirpath) / fn
                rel = p.relative_to(self.root).as_posix().lower()
                self._by_rel[rel] = p
                self._by_name.setdefault(fn.lower(), []).append(p)

    @staticmethod
    def _needles_from_snippet(snippet: str) -> List[str]:
        if not snippet:
            return []
        lines = [ln.strip() for ln in snippet.splitlines() if ln.strip()]
        lines.sort(key=len, reverse=True)
        return [ln for ln in lines if len(ln) >= 6]
