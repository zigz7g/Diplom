# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QRadioButton, QCheckBox,
    QLabel, QPushButton, QFileDialog, QMessageBox, QWidget
)

from services.export.exporters import (
    export_ai_csv, export_warnings_csv, export_full_json, export_markdown_summary
)

class ExportDialog(QDialog):
    """
    Универсальный диалог экспорта. Не тянет данные сам: получает коллбеки.
    """
    def __init__(self,
                 parent: QWidget,
                 collect_warnings_cb,
                 collect_pairs_cb,
                 default_dir: Path):
        super().__init__(parent)
        self.setWindowTitle("Экспорт отчёта")
        self._collect_warnings = collect_warnings_cb
        self._collect_pairs = collect_pairs_cb
        self._default_dir = Path(default_dir)

        v = QVBoxLayout(self)
        v.addWidget(QLabel("Выберите формат экспорта:"))

        self.rb_ai = QRadioButton("CSV: AI-разметка (status/label/comment)")
        self.rb_all = QRadioButton("CSV: все срабатывания (сырые поля)")
        self.rb_json = QRadioButton("JSON: полный отчёт (warning + AI)")
        self.rb_md = QRadioButton("Markdown: краткое резюме")
        self.rb_ai.setChecked(True)

        v.addWidget(self.rb_ai)
        v.addWidget(self.rb_all)
        v.addWidget(self.rb_json)
        v.addWidget(self.rb_md)

        h = QHBoxLayout()
        btn_export = QPushButton("Экспорт…")
        btn_cancel = QPushButton("Отмена")
        h.addWidget(btn_export)
        h.addWidget(btn_cancel)
        v.addLayout(h)

        btn_cancel.clicked.connect(self.reject)
        btn_export.clicked.connect(self._do_export)

    def _do_export(self):
        dst_dir = QFileDialog.getExistingDirectory(
            self, "Выберите папку для экспорта", str(self._default_dir)
        )
        if not dst_dir:
            return
        dst_dir = Path(dst_dir)

        try:
            if self.rb_ai.isChecked():
                out = export_ai_csv(self._collect_pairs(), dst_dir)
            elif self.rb_all.isChecked():
                out = export_warnings_csv(self._collect_warnings(), dst_dir)
            elif self.rb_json.isChecked():
                out = export_full_json(self._collect_pairs(), dst_dir)
            else:
                out = export_markdown_summary(self._collect_pairs(), dst_dir)
        except Exception as e:
            QMessageBox.critical(self, "Экспорт — ошибка", str(e))
            return

        QMessageBox.information(self, "Экспорт завершён", f"Файл сохранён:\n{out}")
        self.accept()
