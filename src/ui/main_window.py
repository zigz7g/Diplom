from __future__ import annotations

from pathlib import Path
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QPlainTextEdit, QFileDialog, QMessageBox,
    QLineEdit, QLabel, QPushButton, QCheckBox, QStatusBar, QToolBar
)

from core.schema import WarningDTO
from data.repositories.in_memory_repository import InMemoryRepository
from services.use_cases import ImportSarifService, ImportCsvService, CodeProvider


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SVACE Annotator")
        self.resize(1280, 800)

        # состояния / сервисы
        self.repo = InMemoryRepository()
        self.import_sarif = ImportSarifService(self.repo)
        self.import_csv = ImportCsvService(self.repo)
        self.code = CodeProvider()
        self._warnings: List[WarningDTO] = []

        # UI
        self._build_ui()
        self._build_actions()

    # ================= UI =================
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Заголовок
        hdr = QHBoxLayout()
        root.addLayout(hdr)
        hdr.addWidget(QLabel("Проект:"))
        self.ed_project = QLineEdit()
        self.ed_project.setPlaceholderText("Название программы / проекта")
        hdr.addWidget(self.ed_project, 1)
        self.lbl_snapshot = QLabel("Снимок: -")
        hdr.addWidget(self.lbl_snapshot)

        # Сплиттер
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # Левая колонка — фильтры + список
        left = QWidget(); left_l = QVBoxLayout(left); left_l.setContentsMargins(0, 0, 0, 0)
        self.ed_search = QLineEdit(placeholderText="Поиск по правилу / файлу / тексту…")
        left_l.addWidget(self.ed_search)
        row_f = QHBoxLayout()
        self.cb_err = QCheckBox("Error"); self.cb_err.setChecked(True)
        self.cb_warn = QCheckBox("Warning"); self.cb_warn.setChecked(True)
        self.cb_note = QCheckBox("Note"); self.cb_note.setChecked(True)
        btn_reset = QPushButton("Сбросить"); btn_reset.clicked.connect(self._reset_filters)
        row_f.addWidget(self.cb_err); row_f.addWidget(self.cb_warn); row_f.addWidget(self.cb_note)
        row_f.addStretch(1); row_f.addWidget(btn_reset)
        left_l.addLayout(row_f)

        self.list = QListWidget()
        left_l.addWidget(self.list, 1)
        splitter.addWidget(left)

        # Центр — ТОЛЬКО код
        self.code_view = QPlainTextEdit(); self.code_view.setReadOnly(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace); mono.setPointSize(10)
        self.code_view.setFont(mono)
        splitter.addWidget(self.code_view)

        # Правая колонка — детали
        right = QWidget(); right_l = QVBoxLayout(right); right_l.setContentsMargins(6, 6, 6, 6)

        def kv(key: str, tgt: QLabel) -> QWidget:
            w = QWidget(); l = QHBoxLayout(w); l.setContentsMargins(0, 0, 0, 0)
            lab = QLabel(key); lab.setMinimumWidth(80)
            l.addWidget(lab); l.addWidget(tgt, 1, Qt.AlignRight); return w

        self.val_rule = QLabel("-")
        self.val_sev = QLabel("-")
        self.val_file = QLabel("-")
        self.val_line = QLabel("-")
        right_l.addWidget(kv("Правило:", self.val_rule))
        right_l.addWidget(kv("Уровень:", self.val_sev))
        right_l.addWidget(kv("Файл:", self.val_file))
        right_l.addWidget(kv("Строка:", self.val_line))

        right_l.addWidget(QLabel("Сообщение анализатора"))
        self.msg_view = QPlainTextEdit(); self.msg_view.setReadOnly(True)
        right_l.addWidget(self.msg_view, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)

        # Статус-бар
        sb = QStatusBar(); self.setStatusBar(sb)
        self.lbl_src_root = QLabel("Исходники: не привязаны")
        sb.addPermanentWidget(self.lbl_src_root)

        # Сигналы
        self.list.currentItemChanged.connect(self._on_item_changed)
        self.ed_search.textChanged.connect(self._populate_list)
        self.cb_err.stateChanged.connect(self._populate_list)
        self.cb_warn.stateChanged.connect(self._populate_list)
        self.cb_note.stateChanged.connect(self._populate_list)

    def _build_actions(self) -> None:
        tb = QToolBar("Main"); self.addToolBar(tb)

        act_open_sarif = QAction("Открыть SARIF", self)
        act_open_csv = QAction("Открыть CSV/TSV", self)
        act_bind_src = QAction("Привязать исходники…", self)
        act_new = QAction("Новый проект", self)

        act_open_sarif.triggered.connect(self._open_sarif)
        act_open_csv.triggered.connect(self._open_csv)
        act_bind_src.triggered.connect(self._pick_sources_root)
        act_new.triggered.connect(self._new_project)

        for a in (act_open_sarif, act_open_csv, act_bind_src, act_new):
            tb.addAction(a)

        m_file = self.menuBar().addMenu("Файл")
        m_file.addAction(act_open_sarif)
        m_file.addAction(act_open_csv)
        m_file.addSeparator()
        m_file.addAction(act_bind_src)
        m_file.addSeparator()
        m_file.addAction(act_new)

    # ============== Команды ==============
    def _new_project(self) -> None:
        self.repo.replace_all([])
        self._warnings.clear()
        self.list.clear(); self.code_view.clear(); self.msg_view.clear()
        self.val_rule.setText("-"); self.val_sev.setText("-"); self.val_file.setText("-"); self.val_line.setText("-")
        self.lbl_snapshot.setText("Снимок: -")

    def _open_sarif(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите SARIF JSON", "", "JSON/SARIF (*.json *.sarif)")
        if not path:
            return
        try:
            n = self.import_sarif.run(path)
            self._warnings = self.repo.list_all()
            self.lbl_snapshot.setText(f"Снимок: {Path(path).name}")
            self._populate_list()
            QMessageBox.information(self, "Импорт SARIF", f"Загружено записей: {n}")
            if self.lbl_src_root.text().endswith("не привязаны"):
                self._pick_sources_root(quiet=True)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    def _open_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите CSV/TSV", "", "CSV/TSV/TXT (*.csv *.tsv *.txt)")
        if not path:
            return
        try:
            n = self.import_csv.run(path)
            self._warnings = self.repo.list_all()
            self.lbl_snapshot.setText(f"Снимок: {Path(path).name}")
            self._populate_list()
            QMessageBox.information(self, "Импорт CSV/TSV", f"Загружено записей: {n}")
            if self.lbl_src_root.text().endswith("не привязаны"):
                self._pick_sources_root(quiet=True)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    def _pick_sources_root(self, quiet: bool = False) -> None:
        d = QFileDialog.getExistingDirectory(self, "Укажите корневую папку исходников")
        if not d:
            if not quiet:
                QMessageBox.information(self, "Исходники",
                                        "Можно привязать исходники позже: Файл → Привязать исходники…")
            return
        self.code.set_root(d)
        self.lbl_src_root.setText(f"Исходники: {d}")
        self._show_current()

    # ============== Список / отображение ==============
    def _reset_filters(self) -> None:
        self.ed_search.clear()
        self.cb_err.setChecked(True)
        self.cb_warn.setChecked(True)
        self.cb_note.setChecked(True)
        self._populate_list()

    def _populate_list(self) -> None:
        """Перестроить список уязвимостей с учётом фильтров и поиска."""
        query = (self.ed_search.text() or "").lower().strip()
        allowed = set()
        if self.cb_err.isChecked(): allowed.add("error")
        if self.cb_warn.isChecked(): allowed.add("warning")
        if self.cb_note.isChecked(): allowed.add("note")

        self.list.clear()
        for w in self._warnings:
            if w.severity not in allowed:
                continue
            blob = " ".join([w.id or "", w.message or "", w.file_path or ""]).lower()
            if query and query not in blob:
                continue
            line = w.start_line if (w.start_line is not None) else "-"
            text = f"[{w.severity}] {w.id} — {Path(w.file_path).name if w.file_path else 'Unknown'}:{line}"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, w)
            self.list.addItem(it)

        if self.list.count() > 0 and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def _on_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        """Слот, который ломался — теперь он есть и показывает детали + код."""
        w: WarningDTO | None = current.data(Qt.UserRole) if current else None
        self._show_warning(w)

    def _show_warning(self, w: WarningDTO | None) -> None:
        """Обновляет правую панель и центр (код) под выбранную уязвимость."""
        if not w:
            self.code_view.clear()
            self.msg_view.clear()
            self.val_rule.setText("-"); self.val_sev.setText("-"); self.val_file.setText("-"); self.val_line.setText("-")
            return

        self.val_rule.setText(w.id or "-")
        self.val_sev.setText(w.severity or "-")
        self.val_file.setText(w.file_path or "Unknown")
        self.val_line.setText(str(w.start_line) if w.start_line is not None else "-")
        self.msg_view.setPlainText(w.message or "")

        # центр — код из исходников
        snippet = self.code.read_snippet(w.file_path, w.start_line, w.end_line, ctx=8)
        self.code_view.setPlainText(snippet or "")

    def _show_current(self) -> None:
        """Перерисовать текущий элемент (после смены корня исходников и т.п.)."""
        it = self.list.currentItem()
        self._on_item_changed(it, None)
