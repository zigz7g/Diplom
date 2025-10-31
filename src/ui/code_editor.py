# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtWidgets import QTextEdit, QWidget
from PySide6.QtGui import (
    QTextCursor,
    QTextCharFormat,
    QColor,
    QFont,
    QTextFormat,
    QPainter,
)
from PySide6.QtCore import Qt, QPoint, QSize


class _LineNumberArea(QWidget):
    """Левая «линейка» с номерами строк."""
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor._line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor._paint_line_number_area(event)


class CodeEditor(QTextEdit):
    """
    Виджет просмотра кода:
      • номера строк (слева),
      • красная подсветка всей проблемной строки,
      • жёлтая подсветка точного диапазона,
      • центрирование по уязвимости при открытии.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.NoWrap)

        # Моноширинный шрифт
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

        # Форматы подсветок
        self._fmt_line = QTextCharFormat()
        self._fmt_line.setBackground(QColor(255, 220, 220))   # красная подложка строки

        self._fmt_range = QTextCharFormat()
        self._fmt_range.setBackground(QColor(255, 235, 150))  # жёлтый точный диапазон

        # Линейка с номерами строк
        self._ln_area = _LineNumberArea(self)
        self._update_ln_margins()

        # Обновления линеек
        self.verticalScrollBar().valueChanged.connect(self._ln_area.update)
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._ln_area.update)

    # ----------------------- Публичное API -----------------------

    def clear_highlight(self):
        self.setExtraSelections([])

    def highlight_range(self, l1: int, c1: int, l2: int, c2: int):
        """
        Подсветить диапазон (l1,c1)-(l2,c2), индексы 1-based.
        Если l2/c2 не заданы — подсветить всю строку l1.
        Автоматически центрирует вид по строке l1.
        """
        sels = []

        # Нормализуем координаты
        l1 = self._clamp_line(l1)
        if not l2 or l2 < 1:
            l2 = l1
        else:
            l2 = self._clamp_line(l2)

        c1 = 1 if not c1 or c1 < 1 else min(c1, self._line_len(l1))
        c2 = self._line_len(l2) if not c2 or c2 < 1 else min(c2, self._line_len(l2))

        # 1) Красная подсветка всей строки l1
        cur_line = QTextCursor(self.document().findBlockByNumber(l1 - 1))
        sel_line = QTextEdit.ExtraSelection()
        sel_line.cursor = cur_line
        sel_line.format = self._fmt_line
        sel_line.format.setProperty(QTextFormat.FullWidthSelection, True)
        sels.append(sel_line)

        # 2) Жёлтая подсветка точного диапазона
        c = QTextCursor(self.document())
        c.setPosition(self._pos(l1, c1))
        c.setPosition(self._pos(l2, c2), QTextCursor.KeepAnchor)
        sel = QTextEdit.ExtraSelection()
        sel.cursor = c
        sel.format = self._fmt_range
        sels.append(sel)

        self.setExtraSelections(sels)

        # 3) Центрирование по первой строке диапазона (как в appScreener)
        self._center_on_line(l1)

    # ----------------------- Внутреннее -----------------------

    def setPlainText(self, text: str) -> None:
        super().setPlainText(text)
        self._update_ln_margins()
        self._ln_area.update()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._update_ln_margins()

    def _on_text_changed(self):
        self._update_ln_margins()
        self._ln_area.update()

    # ---- линейка с номерами строк ----

    def _line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.document().blockCount()))))
        return self.fontMetrics().horizontalAdvance("9" * digits) + 10

    def _update_ln_margins(self):
        w = self._line_number_area_width()
        self.setViewportMargins(w, 0, 0, 0)
        r = self.contentsRect()
        self._ln_area.setGeometry(r.left(), r.top(), w, r.height())

    def _paint_line_number_area(self, event) -> None:
        painter = QPainter(self._ln_area)
        painter.fillRect(event.rect(), QColor("#f3f4f6"))

        fm = self.fontMetrics()
        line_h = fm.lineSpacing()
        height = self.viewport().height()

        first_block = self.cursorForPosition(QPoint(0, 0)).block().blockNumber() + 1
        y = 0
        line_no = first_block
        painter.setPen(QColor("#9ca3af"))

        while y < height:
            painter.drawText(
                0, y, self._ln_area.width() - 4, line_h,
                Qt.AlignRight | Qt.AlignVCenter,
                str(line_no),
            )
            y += line_h
            line_no += 1

    # ---- координаты, длины строк и центрирование ----

    def _clamp_line(self, line: int) -> int:
        if not line or line < 1:
            line = 1
        last = max(1, self.document().blockCount())
        return min(line, last)

    def _line_len(self, line: int) -> int:
        block = self.document().findBlockByNumber(self._clamp_line(line) - 1)
        return max(1, block.length() - 1)  # без завершающего \n

    def _pos(self, line: int, col: int) -> int:
        line = self._clamp_line(line)
        col = 1 if not col or col < 1 else min(col, self._line_len(line))
        block = self.document().findBlockByNumber(line - 1)
        return block.position() + (col - 1)

    def _center_on_line(self, line: int, top_margin_lines: int = 0):
        """
        Жёсткое центрирование вертикального скролла так, чтобы строка
        оказалась примерно посередине видимой области (как в appScreener).
        """
        line = self._clamp_line(line)
        vbar = self.verticalScrollBar()
        if vbar is None:
            return

        # Пиксельные метрики
        fm = self.fontMetrics()
        line_h = max(1, fm.lineSpacing())
        viewport_h = max(1, self.viewport().height())

        # желаемый верхний край области прокрутки
        desired_top = int(line_h * (line - 1 - top_margin_lines) - (viewport_h - line_h) / 2)
        val = max(vbar.minimum(), min(vbar.maximum(), desired_top))
        vbar.setValue(val)

        # горизонтально убедимся, что курсор виден
        block = self.document().findBlockByNumber(line - 1)
        cur = QTextCursor(block)
        self.setTextCursor(cur)
        self.ensureCursorVisible()
