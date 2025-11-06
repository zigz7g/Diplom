# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QFontDatabase, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QWidget, QPlainTextEdit, QTextEdit


class _LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor._line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor._paint_line_number_area(event)


class CodeEditor(QPlainTextEdit):
    """
    Редактор кода с номерами строк, подсветкой строк/диапазона и прокруткой к строке.
      API:
        - set_code(text: str)
        - clear_highlight()
        - highlight_lines(lines: Iterable[int])
        - highlight_range(l1: int, c1: int|None, l2: int, c2: int|None)
        - scroll_to_line(line: int)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_number_area = _LineNumberArea(self)
        self._highlight_lines = set()      # {int}
        self._range = None                 # (l1, c1, l2, c2) | None

        # отображение
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPointSize(11)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)

        # обновления
        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)

        self._update_line_number_area_width(0)
        self._highlight_current_line()

    # ---------- public API ----------

    def set_code(self, text: str) -> None:
        self.setPlainText(text)

    def clear_highlight(self) -> None:
        self._highlight_lines.clear()
        self._range = None
        self._apply_highlight()

    def highlight_lines(self, lines) -> None:
        self._highlight_lines = {int(x) for x in lines if isinstance(x, int) and x > 0}
        self._apply_highlight()

    def highlight_range(self, l1: int, c1: int | None, l2: int, c2: int | None) -> None:
        # нормализация
        if not l1 or l1 < 1: l1 = 1
        if not l2 or l2 < l1: l2 = l1
        c1 = 1 if not c1 or c1 < 1 else int(c1)
        c2 = 0 if not c2 else int(c2)  # 0 = до конца строки
        self._range = (int(l1), c1, int(l2), c2)
        self._apply_highlight()
        self.scroll_to_line(l1)

    def scroll_to_line(self, line: int) -> None:
        if not line or line <= 0:
            return
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.centerCursor()

    # ---------- internals ----------

    def _line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _):
        self.setViewportMargins(self._line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QRect(cr.left(), cr.top(), self._line_number_area_width(), cr.height())
        )

    def _paint_line_number_area(self, event):
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor("#F1F5F9"))  # фон
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        right = self._line_number_area.width() - 6

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#64748B"))
                painter.drawText(0, top, right, self.fontMetrics().height(),
                                 Qt.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def _highlight_current_line(self):
        self._apply_highlight()

    def _apply_highlight(self):
        sels: list[QTextEdit.ExtraSelection] = []

        # текущая строка
        cur_fmt = QTextCharFormat(); cur_fmt.setBackground(QColor("#EEF2FF"))
        cur_sel = QTextEdit.ExtraSelection()
        cur_sel.format = cur_fmt
        cur_sel.cursor = self.textCursor()
        cur_sel.cursor.clearSelection()
        sels.append(cur_sel)

        # подсветка простых строк
        if self._highlight_lines:
            hl_fmt = QTextCharFormat(); hl_fmt.setBackground(QColor("#FECACA"))  # светло-красный
            for ln in sorted(self._highlight_lines):
                block = self.document().findBlockByNumber(ln - 1)
                if not block.isValid():
                    continue
                sel = QTextEdit.ExtraSelection()
                sel.format = hl_fmt
                cursor = self.textCursor()
                cursor.setPosition(block.position())
                cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                sel.cursor = cursor
                sels.append(sel)

        # подсветка диапазона
        if self._range:
            l1, c1, l2, c2 = self._range
            fmt = QTextCharFormat(); fmt.setBackground(QColor("#FCA5A5"))  # чуть насыщеннее
            start_block = self.document().findBlockByNumber(max(0, l1 - 1))
            end_block   = self.document().findBlockByNumber(max(0, l2 - 1))
            if start_block.isValid() and end_block.isValid():
                start_pos = start_block.position() + max(0, c1 - 1)
                end_pos   = (end_block.position() + (end_block.length() - 1)) if c2 == 0 else \
                            (end_block.position() + max(0, c2 - 1))
                cur = self.textCursor()
                cur.setPosition(start_pos)
                cur.setPosition(max(start_pos, end_pos), QTextCursor.KeepAnchor)
                sel = QTextEdit.ExtraSelection()
                sel.format = fmt
                sel.cursor = cur
                sels.append(sel)

        self.setExtraSelections(sels)
