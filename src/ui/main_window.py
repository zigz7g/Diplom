# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict
from traceback import format_exc

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QLabel, QFileDialog,
    QLineEdit, QCheckBox, QPushButton, QFormLayout, QSizePolicy,
    QMessageBox, QDialog
)

from core.schema import WarningDTO, SEVERITY_COLORS
from data.repositories.in_memory_repository import InMemoryRepository
from services.code_provider import CodeProvider
from services.use_cases import ImportSarifService, ImportCsvService
from ui.code_editor import CodeEditor
from ui.annotate_dialog import AnnotateDialog


# ---------- helpers ----------

def _read_text_best_effort(p: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "windows-1251", "utf-16", "utf-32", "iso-8859-1"):
        try:
            return p.read_text(encoding=enc)
        except Exception:
            pass
    return p.read_bytes().decode("utf-8", errors="replace")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SVACE Annotator — AI static report assistant")
        self.resize(1280, 760)

        self.repo = InMemoryRepository()
        self.import_sarif = ImportSarifService(self.repo)
        self.import_csv = ImportCsvService(self.repo)

        self.source_root: Optional[Path] = None
        self.code = CodeProvider(None)

        # ---------- UI ----------
        root = QWidget(self); self.setCentralWidget(root)
        layout = QVBoxLayout(root); layout.setContentsMargins(10, 10, 10, 10); layout.setSpacing(8)

        top = QHBoxLayout()
        self.ed_title = QLineEdit(placeholderText="Название программы / проекта")
        self.ed_search = QLineEdit(placeholderText="Поиск по правилу / файлу / тексту…")
        self.lab_snapshot = QLabel("Снимок: —")
        self.lab_snapshot.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lab_snapshot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self.ed_title, 2); top.addWidget(self.ed_search, 3); top.addWidget(self.lab_snapshot, 1)
        layout.addLayout(top)

        filters = QHBoxLayout(); filters.setSpacing(10)
        self.cb_crit = QCheckBox("Critical"); self.cb_crit.setChecked(True)
        self.cb_med = QCheckBox("Medium"); self.cb_med.setChecked(True)
        self.cb_low = QCheckBox("Low"); self.cb_low.setChecked(True)
        self.cb_info = QCheckBox("Info"); self.cb_info.setChecked(True)
        self.cb_group = QCheckBox("Группировать по правилу"); self.cb_group.setChecked(True)
        for cb in (self.cb_crit, self.cb_med, self.cb_low, self.cb_info, self.cb_group):
            filters.addWidget(cb)
        filters.addStretch(1)
        self.btn_reset = QPushButton("Сбросить"); filters.addWidget(self.btn_reset)
        layout.addLayout(filters)

        split = QSplitter(Qt.Horizontal); split.setHandleWidth(4); layout.addWidget(split, 1)

        self.tree = QTreeWidget(); self.tree.setHeaderHidden(True); split.addWidget(self.tree)
        self.code_view = CodeEditor(); split.addWidget(self.code_view)

        right = QWidget(); r = QVBoxLayout(right); r.setContentsMargins(8, 0, 0, 0); r.setSpacing(8)
        form = QFormLayout()
        self.lab_rule = QLabel("-")
        self.lab_sev = QLabel("-")
        self.lab_file = QLabel("-")
        self.lab_line = QLabel("-")
        self.lab_status = QLabel("Не обработано")
        for lab in (self.lab_rule, self.lab_sev, self.lab_file, self.lab_line, self.lab_status):
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Правило:", self.lab_rule)
        form.addRow("Уровень:", self.lab_sev)
        form.addRow("Файл:", self.lab_file)
        form.addRow("Строка:", self.lab_line)
        form.addRow("Статус:", self.lab_status)
        r.addLayout(form)

        self.ed_message = QTextEdit(); self.ed_message.setReadOnly(True); self.ed_message.setMinimumHeight(70)
        r.addWidget(self.ed_message, 1)

        self.ed_comment_view = QTextEdit(); self.ed_comment_view.setReadOnly(True); self.ed_comment_view.setMinimumHeight(90)
        r.addWidget(self.ed_comment_view, 1)

        self.btn_annotate = QPushButton("Разметить…"); self.btn_annotate.setEnabled(False)
        r.addWidget(self.btn_annotate, 0, Qt.AlignBottom)
        split.addWidget(right)
        split.setSizes([420, 820, 320])

        # Меню
        menu_file = self.menuBar().addMenu("Файл")
        self.act_open_sarif = QAction("Открыть SARIF", self)
        self.act_bind_src = QAction("Привязать исходники…", self)
        menu_file.addAction(self.act_open_sarif); menu_file.addAction(self.act_bind_src)

        # Сигналы
        self.tree.itemSelectionChanged.connect(self._on_item_changed)
        self.ed_search.textChanged.connect(lambda *_: self._reload_filtered())
        for cb in (self.cb_crit, self.cb_med, self.cb_low, self.cb_info, self.cb_group):
            cb.stateChanged.connect(lambda *_: self._reload_filtered())
        self.btn_reset.clicked.connect(self._reset_filters)
        self.btn_annotate.clicked.connect(self._annotate_current)
        self.act_open_sarif.triggered.connect(self._open_sarif)
        self.act_bind_src.triggered.connect(self._pick_source_root)

        self._all: List[WarningDTO] = []
        self._reload_filtered()

    # ---------- actions ----------

    def _reset_filters(self) -> None:
        self.ed_search.clear()
        for cb in (self.cb_crit, self.cb_med, self.cb_low, self.cb_info):
            cb.setChecked(True)

    def set_snapshot_name(self, name: str) -> None:
        self.lab_snapshot.setText(f"Снимок: {name}")

    def load_items(self, items: List[WarningDTO]) -> None:
        self._all = list(items)
        self._reload_filtered()

    def _open_sarif(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть SARIF", "", "SARIF/JSON (*.sarif *.json);;All (*.*)")
        if not path:
            return
        try:
            n = self.import_sarif.run(path)
            QMessageBox.information(self, "Импорт SARIF", f"Загружено записей: {n}")
            self.set_snapshot_name(Path(path).name)
            self.load_items(self.repo.list_all())

            # Привязать исходники сразу после импорта (если не задано)
            if not self.source_root:
                if QMessageBox.question(
                    self, "Исходники",
                    "Привязать каталог исходников для подсветки строк?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                ) == QMessageBox.Yes:
                    self._pick_source_root()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта SARIF", f"{e}\n\n{format_exc()}")

    def _pick_source_root(self) -> None:
        dir_ = QFileDialog.getExistingDirectory(self, "Выбрать корень исходников", "")
        if not dir_:
            return
        self.source_root = Path(dir_)
        self.code.set_root(self.source_root)
        QMessageBox.information(self, "Исходники", f"Привязан каталог исходников:\n{self.source_root}")

    # ---------- list render ----------

    def _reload_filtered(self) -> None:
        text = self.ed_search.text().strip().lower()
        enabled = {
            "critical": self.cb_crit.isChecked(),
            "medium": self.cb_med.isChecked(),
            "low": self.cb_low.isChecked(),
            "info": self.cb_info.isChecked(),
        }

        self.tree.clear()
        items: List[WarningDTO] = []
        for w in self._all:
            sev = w.eff_severity()
            if not enabled.get(sev, True):
                continue
            if text:
                blob = f"{w.rule_id} {w.message} {w.file}:{getattr(w,'line','-')}".lower()
                if text not in blob:
                    continue
            items.append(w)

        if self.cb_group.isChecked():
            by_rule: Dict[str, List[WarningDTO]] = {}
            for w in items:
                by_rule.setdefault(w.rule_id or "(no-rule)", []).append(w)
            for rule, warnings in sorted(by_rule.items(), key=lambda kv: kv[0].lower()):
                head = QTreeWidgetItem([f"{rule} — {len(warnings)}"])
                head.setFirstColumnSpanned(True); head.setData(0, Qt.UserRole, None)
                self.tree.addTopLevelItem(head)
                for w in warnings:
                    leaf = QTreeWidgetItem([self._leaf_caption(w)])
                    leaf.setData(0, Qt.UserRole, w)
                    color = QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827"))
                    leaf.setForeground(0, color)
                    head.addChild(leaf)
                head.setExpanded(True)
        else:
            for w in items:
                it = QTreeWidgetItem([self._leaf_caption(w)])
                it.setData(0, Qt.UserRole, w)
                color = QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827"))
                it.setForeground(0, color)
                self.tree.addTopLevelItem(it)

        self.btn_annotate.setEnabled(False)
        if self.tree.topLevelItemCount() > 0:
            first = self.tree.topLevelItem(0)
            sel = first.child(0) if first and first.childCount() > 0 else first
            self.tree.setCurrentItem(sel)

    def _leaf_caption(self, w: WarningDTO) -> str:
        mark = ""
        if w.status == "Подтверждено": mark = "  ✔"
        elif w.status == "Отклонено":   mark = "  ✖"
        return f"[{w.eff_severity()}] {w.file}:{getattr(w, 'line', '-')} {mark}"

    # ---------- selection ----------

    def _on_item_changed(self) -> None:
        item = self.tree.currentItem()
        if not item:
            self._clear_details(); return
        w = item.data(0, Qt.UserRole)
        if not isinstance(w, WarningDTO):
            self._clear_details(); return

        self._show_details(w)
        self._show_snippet(w)
        self.btn_annotate.setEnabled(True)

    def _clear_details(self) -> None:
        self.lab_rule.setText("-"); self.lab_sev.setText("-")
        self.lab_file.setText("-"); self.lab_line.setText("-")
        self.lab_status.setText("Не обработано")
        self.ed_message.setPlainText(""); self.ed_comment_view.setPlainText("")
        self.code_view.setPlainText("")
        self.code_view.clear_highlight()
        self.btn_annotate.setEnabled(False)

    def _show_details(self, w: WarningDTO) -> None:
        self.lab_rule.setText(w.rule_id or "-")
        self.lab_sev.setText(w.eff_severity())
        self.lab_file.setText(w.file or "-")
        self.lab_line.setText(str(getattr(w, "start_line", None) or getattr(w, "line", "-")))
        self.lab_status.setText(w.status or "Не обработано")
        self.ed_message.setPlainText(w.message or "")
        self.ed_comment_view.setPlainText(w.comment or "")

    def _resolve_fs_path(self, w: WarningDTO) -> Optional[Path]:
        if self.source_root is None:
            return None
        return self.code.find(w.file)

    def _show_snippet(self, w: WarningDTO) -> None:
        """
        Логика показа кода:
        1) пытаемся открыть физический файл из привязанного каталога;
        2) если нет — показываем сниппет из SARIF и подсвечиваем целиком;
        3) если есть файл — подсвечиваем диапазон из SARIF.
        """
        text_is_set = False

        # 1) локальный файл
        p = self._resolve_fs_path(w)
        if p and p.exists():
            try:
                self.code_view.setPlainText(_read_text_best_effort(p))
                text_is_set = True
            except Exception:
                pass

        # 2) сниппет (если файла нет)
        if not text_is_set:
            snippet = (
                getattr(w, "snippet_text", None)
                or getattr(w, "snippet", None)
                or ""
            )
            self.code_view.setPlainText(snippet)
            self.code_view.clear_highlight()
            if snippet:
                total_lines = snippet.count("\n") + 1
                self.code_view.highlight_range(1, 1, total_lines, None)
            return

        # 3) подсветка диапазона из SARIF
        l1 = int(getattr(w, "start_line", None) or getattr(w, "line", 1))
        c1 = int(getattr(w, "start_col", 1) or 1)
        l2 = int(getattr(w, "end_line", None) or l1)
        c2 = int(getattr(w, "end_col", None) or 0)
        if c2 == 0:
            # если колонка не задана — подсветим всю строку
            self.code_view.highlight_range(l1, 1, l1, None)
        else:
            self.code_view.highlight_range(l1, c1, l2, c2)

    # ---------- annotate ----------

    def _annotate_current(self) -> None:
        item = self.tree.currentItem()
        if not item:
            return
        w = item.data(0, Qt.UserRole)
        if not isinstance(w, WarningDTO):
            return

        dlg = AnnotateDialog(self, w.status or "Не обработано", w.eff_severity(), w.comment or "")
        if dlg.exec() == QDialog.Accepted:
            status, sev, comment = dlg.chosen()
            w.status = status
            w.severity_ui = sev
            w.comment = comment

            # обновим правую панель и подпись элемента
            self._show_details(w)
            item.setText(0, self._leaf_caption(w))
            item.setForeground(0, QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827")))
