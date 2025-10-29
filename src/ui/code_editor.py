# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor, QFont, QTextFormat
from PySide6.QtCore import Qt


class CodeEditor(QTextEdit):
    """
    Просмотр кода с подсветкой диапазона и прокруткой к нему.
    Работает без centerCursor() (которого нет в некоторых сборках PySide6).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.NoWrap)

        # Моноширинный шрифт + запасные
        f = QFont()
        try:
            f.setFamilies([
                "Cascadia Mono", "JetBrains Mono", "Noto Sans Mono",
                "Consolas", "DejaVu Sans Mono", "Courier New", "Segoe UI"
            ])
        except Exception:
            f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        f.setPointSize(10)
        self.setFont(f)

        # Форматы подсветки
        self._fmt_range = QTextCharFormat()
        self._fmt_range.setBackground(QColor(255, 235, 150))   # жёлтый
        self._fmt_line = QTextCharFormat()
        self._fmt_line.setBackground(QColor(245, 245, 245))    # серая подложка

    # ----------------------- ВСПОМОГАТЕЛЬНЫЕ -----------------------

    def clear_highlight(self):
        self.setExtraSelections([])

    def _clamp_line(self, line: int) -> int:
        if line is None or line < 1:
            line = 1
        last = self.document().blockCount()
        if last <= 0:
            last = 1
        if line > last:
            line = last
        return line

    def _line_len(self, line: int) -> int:
        line = self._clamp_line(line)
        block = self.document().findBlockByNumber(line - 1)
        return max(1, block.length() - 1)  # без '\n'

    def _pos(self, line: int, col: int) -> int:
        line = self._clamp_line(line)
        col = 1 if col is None or col < 1 else col
        block = self.document().findBlockByNumber(line - 1)
        # не выходим за пределы строки
        col = min(col, self._line_len(line))
        return block.position() + (col - 1)

    def _scroll_to_cursor(self, cur: QTextCursor):
        """
        Прокрутка так, чтобы подсвеченный диапазон был виден и примерно по центру.
        В некоторых сборках нет centerCursor(), поэтому используем ensureCursorVisible()
        и небольшую коррекцию скролла.
        """
        self.setTextCursor(cur)
        self.ensureCursorVisible()

        # Пытаемся центрировать область вручную
        try:
            vbar = self.verticalScrollBar()
            rng = vbar.maximum() - vbar.minimum()
            if rng > 0:
                # небольшой сдвиг к центру (эвристика)
                vbar.setValue(max(vbar.minimum(), min(vbar.maximum(), vbar.value() - int(rng * 0.05))))
        except Exception:
            pass

    # ----------------------- ПУБЛИЧНОЕ API -----------------------

    def highlight_range(self, l1: int, c1: int, l2: int, c2: int):
        """
        Подсветка строк/диапазона (l1,c1)-(l2,c2). Все индексы 1-based.
        Если end не задан — подсвечивается вся строка l1.
        """
        sels = []

        # 1) фон для всей строки
        cur_line = QTextCursor(self.document().findBlockByNumber(self._clamp_line(l1) - 1))
        sel_line = QTextEdit.ExtraSelection()
        sel_line.cursor = cur_line
        sel_line.format = self._fmt_line
        sel_line.format.setProperty(QTextFormat.FullWidthSelection, True)
        sels.append(sel_line)

        # 2) точный диапазон (если есть)
        if l2 is None or l2 < 1:
            l2 = l1
        if c2 is None or c2 < 1:
            # если нет конечной колонки — берём до конца строки
            c2 = self._line_len(l2)

        c = QTextCursor(self.document())
        c.setPosition(self._pos(l1, c1))
        c.setPosition(self._pos(l2, c2), QTextCursor.KeepAnchor)

        sel = QTextEdit.ExtraSelection()
        sel.cursor = c
        sel.format = self._fmt_range
        sels.append(sel)

        self.setExtraSelections(sels)
        self._scroll_to_cursor(c)
