# -*- coding: utf-8 -*-
from __future__ import annotations

from ui.export_dialog import ExportDialog

import os, json, csv
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from traceback import format_exc

from PySide6.QtCore import Qt, QObject, Signal, Slot, QThread
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QLabel, QFileDialog,
    QLineEdit, QCheckBox, QPushButton, QFormLayout, QSizePolicy,
    QMessageBox, QDialog, QProgressDialog
)
from services.analysis.heuristics import analyze_warning
from core.schema import WarningDTO, SEVERITY_COLORS
from data.repositories.in_memory_repository import InMemoryRepository
from services.code_provider import CodeProvider
from services.use_cases import ImportSarifService
from ui.code_editor import CodeEditor
from ui.annotate_dialog import AnnotateDialog

# LLM
from services.llm.yagpt_client import YandexGPTClient
from services.llm.annotator import AIAnnotator


# ---------- helpers ----------

def _read_text_best_effort(p: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1251", "windows-1251", "utf-16", "utf-32", "iso-8859-1"):
        try:
            return p.read_text(encoding=enc)
        except Exception:
            pass
    return p.read_bytes().decode("utf-8", errors="replace")


def _load_env_from_nearby(repo_hint: Optional[Path]) -> Optional[Path]:
    """
    Ищет .env в корне проекта и выше и загружает пары KEY=VALUE в os.environ,
    не перезаписывая уже выставленные переменные окружения.
    """
    def _apply(path: Path) -> None:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

    candidates: list[Path] = []
    if repo_hint:
        candidates += [
            repo_hint / ".env",
            repo_hint.parent / ".env",
            repo_hint.parent.parent / ".env",
        ]
    candidates += [Path.cwd() / ".env"]

    for p in candidates:
        try:
            if p and p.exists():
                _apply(p)
                return p
        except Exception:
            pass
    return None


# ---------- AI worker (отдельный поток) ----------

class _AIWorker(QObject):
    started = Signal(int)                         # total
    progressed = Signal(int, object, object)      # i, WarningDTO, ai_result
    error = Signal(str)
    finished = Signal()

    def __init__(self, annotator: AIAnnotator, warnings: List[WarningDTO], code: CodeProvider):
        super().__init__()
        self.annotator = annotator
        self.warnings = [w for w in warnings if isinstance(w, WarningDTO)]
        self.code = code
        self._stop = False

    @Slot()
    def run(self):
        try:
            total = len(self.warnings)
            self.started.emit(total)
            for i, w in enumerate(self.warnings, 1):
                if self._stop:
                    break

                # контекст: полный текст файла (если есть)
                file_text = ""
                try:
                    p = self.code.find(getattr(w, "file", "") or "")
                    if p and p.exists():
                        file_text = _read_text_best_effort(p)
                except Exception:
                    file_text = ""

                # вызов аннотатора — передаём параметры явно
                try:
                    # фрагмент вокруг срабатывания: сначала snippet из отчёта, при его отсутствии – пустая строка
                    code_snippet = (
                            getattr(w, "snippet_text", None)
                            or getattr(w, "snippet", None)
                            or ""
                    )

                    # номер строки: сначала start_line (новая схема), иначе line (старая), по умолчанию 0
                    line_no = (
                            getattr(w, "start_line", None)
                            or getattr(w, "line", None)
                            or 0
                    )

                    # путь к файлу: поддерживаем и file_path, и старое file
                    file_path = (
                            getattr(w, "file_path", None)
                            or getattr(w, "file", "")
                            or ""
                    )

                    # текст сообщения статического анализатора
                    text_msg = getattr(w, "message", "") or ""

                    res = self.annotator.annotate_one(
                        rule=w.rule_id or "",
                        level=w.severity_ui or w.severity or "",
                        file_path=file_path,
                        line=int(line_no),
                        code=code_snippet,
                        text=text_msg,
                        status=getattr(w, "status", "") or "",
                    )
                except Exception as e:
                    self.error.emit(str(e))
                    continue

                self.progressed.emit(i, w, res)

            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit()

    def stop(self):
        self._stop = True


# ---------- Main Window ----------

class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SVACE Annotator — AI static report assistant")
        self.resize(1280, 760)

        self.repo = InMemoryRepository()
        self.import_sarif = ImportSarifService(self.repo)

        self.source_root: Optional[Path] = None
        self.code = CodeProvider(None)

        # 1) корень проекта и .env
        try:
            self.project_root: Path = Path(__file__).resolve().parents[2]
        except Exception:
            self.project_root = Path.cwd()
        _load_env_from_nearby(self.project_root)

        # 2) каталог отчётов
        self.reports_dir: Path = self.project_root / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._snapshot_name: str = "—"

        # 3) клиент LLM после загрузки ENV
        self.ai_client = YandexGPTClient(
            api_key=os.getenv("YAGPT_API_KEY") or os.getenv("YA_API_KEY") or "",
            folder_id=os.getenv("YAGPT_FOLDER_ID") or os.getenv("YA_FOLDER_ID") or "",
            model_name=os.getenv("YAGPT_MODEL", "yandexgpt"),
        )
        self.ai = AIAnnotator(client=self.ai_client)

        # кто размечен ИИ
        self._ai_marked: set[int] = set()

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

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        split.addWidget(self.tree)

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

        # Кнопки действий
        row_btns = QHBoxLayout()
        self.btn_ai = QPushButton("Авторазметка (ЯндексGPT)"); self.btn_ai.setEnabled(False)
        self.btn_annotate = QPushButton("Разметить…"); self.btn_annotate.setEnabled(False)
        row_btns.addWidget(self.btn_ai)
        row_btns.addWidget(self.btn_annotate)
        r.addLayout(row_btns)

        split.addWidget(right)
        split.setSizes([420, 820, 320])

        # Меню
        menu_file = self.menuBar().addMenu("Файл")
        self.act_open_sarif = QAction("Открыть SARIF…", self)
        self.act_bind_src = QAction("Привязать исходники…", self)
        menu_file.addAction(self.act_open_sarif); menu_file.addAction(self.act_bind_src)

        menu_project = self.menuBar().addMenu("Проект")
        self.act_ai_selected = QAction("Авторазметка — выделенные", self)
        self.act_ai_all_filtered = QAction("Авторазметка — все (фильтр)", self)
        self.act_ai_whole = QAction("Авторазметка — весь проект", self)
        menu_project.addAction(self.act_ai_selected)
        menu_project.addAction(self.act_ai_all_filtered)
        menu_project.addAction(self.act_ai_whole)

        # ЕДИНЫЙ экспорт
        menu_export = self.menuBar().addMenu("Экспорт")
        self.act_export_unified = QAction("Экспорт…", self)
        menu_export.addAction(self.act_export_unified)

        # Стиль
        self.setStyleSheet("""
        QMainWindow { background: #f8fafc; }
        QLineEdit, QTextEdit { background:#ffffff; border:1px solid #E5E7EB; border-radius:8px; padding:6px 10px; }
        QTreeWidget { border:1px solid #E5E7EB; border-radius:8px; }
        QSplitter::handle { background:#E5E7EB; }
        QPushButton { background:#111827; color:#ffffff; border:0; border-radius:8px; padding:6px 12px; }
        QPushButton:disabled { background:#9CA3AF; }
        QMenuBar { background:#111827; color:#e5e7eb; }
        QMenuBar::item { padding:6px 12px; background:transparent; }
        QMenuBar::item:selected { background:#374151; }
        QMenu { background:#1F2937; color:#e5e7eb; border:1px solid #374151; }
        QMenu::item:selected { background:#374151; }
        """)

        # Сигналы
        self.tree.itemSelectionChanged.connect(self._on_item_changed)
        self.ed_search.textChanged.connect(lambda *_: self._reload_filtered())
        for cb in (self.cb_crit, self.cb_med, self.cb_low, self.cb_info, self.cb_group):
            cb.stateChanged.connect(lambda *_: self._reload_filtered())
        self.btn_reset.clicked.connect(self._reset_filters)

        self.btn_ai.clicked.connect(self._ai_clicked)
        self.btn_annotate.clicked.connect(self._annotate_current)

        self.act_open_sarif.triggered.connect(self._open_sarif)
        self.act_bind_src.triggered.connect(self._pick_source_root)

        self.act_ai_selected.triggered.connect(self._ai_clicked)
        self.act_ai_all_filtered.triggered.connect(self._ai_clicked_all)
        self.act_ai_whole.triggered.connect(self._ai_clicked_whole)

        self.act_export_unified.triggered.connect(self._open_export_dialog)

        # состояние
        self._all: List[WarningDTO] = []
        self._filtered: List[WarningDTO] = []
        self._warn_item_map: Dict[int, QTreeWidgetItem] = {}
        self._reload_filtered()

    # ---------- actions ----------

    def _reset_filters(self) -> None:
        self.ed_search.clear()
        for cb in (self.cb_crit, self.cb_med, self.cb_low, self.cb_info):
            cb.setChecked(True)

    def set_snapshot_name(self, name: str) -> None:
        self._snapshot_name = name or "—"
        self.lab_snapshot.setText(f"Снимок: {self._snapshot_name}")

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
        self._warn_item_map.clear()
        items: List[WarningDTO] = []
        for w in self._all:
            sev = (w.eff_severity() or "").lower()
            if not enabled.get(sev or "medium", True):
                continue
            if text:
                blob = f"{w.rule_id} {w.message} " \
                       f"{getattr(w,'file','') or getattr(w,'file_path','')}:" \
                       f"{getattr(w,'start_line',None) or getattr(w,'line','-')}".lower()
                if text not in blob:
                    continue
            items.append(w)
        self._filtered = items

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
                    self._warn_item_map[id(w)] = leaf
                head.setExpanded(True)
        else:
            for w in items:
                it = QTreeWidgetItem([self._leaf_caption(w)])
                it.setData(0, Qt.UserRole, w)
                color = QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827"))
                it.setForeground(0, color)
                self.tree.addTopLevelItem(it)
                self._warn_item_map[id(w)] = it

        self.btn_annotate.setEnabled(False)
        self.btn_ai.setEnabled(False)
        if self.tree.topLevelItemCount() > 0:
            first = self.tree.topLevelItem(0)
            sel = first.child(0) if first and first.childCount() > 0 else first
            self.tree.setCurrentItem(sel)

    def _leaf_caption(self, w: WarningDTO) -> str:
        mark = ""
        if w.status == "Подтверждено":
            mark = "  ✔"
        elif w.status == "Отклонено":
            mark = "  ✖"

        file_ = getattr(w, "file", "") or getattr(w, "file_path", "") or "-"
        line_ = getattr(w, "start_line", None) or getattr(w, "line", None) or "-"
        return f"[{w.eff_severity()}] {file_}:{line_}{mark}"

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
        self.btn_ai.setEnabled(True)

    def _clear_details(self) -> None:
        self.lab_rule.setText("-"); self.lab_sev.setText("-")
        self.lab_file.setText("-"); self.lab_line.setText("-")
        self.lab_status.setText("Не обработано")
        self.ed_message.setPlainText(""); self.ed_comment_view.setPlainText("")
        self.code_view.setPlainText("")
        self.code_view.clear_highlight()
        self.btn_annotate.setEnabled(False)
        self.btn_ai.setEnabled(False)

    def _show_details(self, w: WarningDTO) -> None:
        self.lab_rule.setText(w.rule_id or "-")
        self.lab_sev.setText(w.eff_severity())
        file_ = getattr(w, "file", "") or getattr(w, "file_path", "") or "-"
        self.lab_file.setText(file_)
        line_ = getattr(w, "start_line", None) or getattr(w, "line", None) or "-"
        self.lab_line.setText(str(line_))
        self.lab_status.setText(getattr(w, "status", None) or "Не обработано")
        self.ed_message.setPlainText(w.message or "")
        self.ed_comment_view.setPlainText(getattr(w, "comment", "") or "")

    def _resolve_fs_path(self, w: WarningDTO) -> Optional[Path]:
        if self.source_root is None:
            return None

        raw = (getattr(w, "file", "") or getattr(w, "file_path", "") or "").strip()
        if not raw:
            return None

        # Нормализация
        rel = Path(raw.replace("\\", "/"))
        root = self.source_root

        # 1) Абсолютный путь
        if rel.is_absolute() and rel.exists():
            return rel

        # 2) Прямое соединение
        cand = root / rel
        if cand.exists():
            return cand

        # 3) Удаление дублирующей верхней папки (root.name == rel.parts[0])
        try:
            parts = rel.parts
            if parts and parts[0].lower() == root.name.lower():
                cand2 = root.joinpath(*parts[1:])
                if cand2.exists():
                    return cand2
        except Exception:
            pass

        # 4) Поиск по суффиксу внутри root (лучшее совпадение по хвосту пути)
        try:
            target_suffix = str(rel.as_posix()).lower()
            candidates = []
            for found in root.rglob(rel.name):
                f_rel = str(found.relative_to(root).as_posix()).lower()
                if f_rel.endswith(target_suffix):
                    return found
                candidates.append((found, f_rel))

            if candidates:
                target_parts = list(rel.parts)[::-1]
                best, best_score = None, -1
                for f, f_rel in candidates:
                    cand_parts = f_rel.split("/")[::-1]
                    score = 0
                    for a, b in zip(target_parts, cand_parts):
                        if a.lower() == b.lower():
                            score += 1
                        else:
                            break
                    if score > best_score:
                        best, best_score = f, score
                return best
        except Exception:
            pass

        return None

    def _show_snippet(self, w: WarningDTO) -> None:
        """
        1) если нашли файл — показываем его и подсвечиваем диапазон из SARIF;
        2) если нет — показываем сниппет и подсвечиваем его целиком.
        """
        p = self._resolve_fs_path(w)
        if p and p.exists():
            try:
                text = _read_text_best_effort(p)
                self.code_view.setPlainText(text)
            except Exception:
                text = ""
                self.code_view.setPlainText(text)

            l1 = int(getattr(w, "start_line", None) or getattr(w, "line", 1) or 1)
            c1 = int(getattr(w, "start_col", 1) or 1)
            l2 = int(getattr(w, "end_line", None) or l1 or 1)
            c2 = int(getattr(w, "end_col", None) or 0)

            total_lines = (text.count("\n") + 1) if text else 1
            l1 = max(1, min(l1, total_lines))
            l2 = max(l1, min(l2, total_lines))
            c1 = max(1, c1)
            if c2 == 0:
                self.code_view.highlight_range(l1, c1, l1, None)
            else:
                self.code_view.highlight_range(l1, c1, l2, max(c1, c2))
            return

        snippet = (getattr(w, "snippet_text", None) or getattr(w, "snippet", None) or "")
        self.code_view.setPlainText(snippet)
        self.code_view.clear_highlight()
        if snippet:
            total_lines = snippet.count("\n") + 1
            self.code_view.highlight_range(1, 1, total_lines, None)

    # ---------- ручная разметка ----------

    def _annotate_current(self) -> None:
        item = self.tree.currentItem()
        if not item:
            return
        w = item.data(0, Qt.UserRole)
        if not isinstance(w, WarningDTO):
            return

        dlg = AnnotateDialog(self, getattr(w, "status", "") or "Не обработано",
                             w.eff_severity(), getattr(w, "comment", "") or "")
        if dlg.exec() == QDialog.Accepted:
            status, sev, comment = dlg.chosen()
            w.status = status
            w.severity_ui = sev
            w.comment = comment

            self._show_details(w)
            it = self._warn_item_map.get(id(w))
            if it:
                it.setText(0, self._leaf_caption(w))
                it.setForeground(0, QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827")))

    # ---------- AI разметка ----------

    def _collect_selected_warnings(self) -> List[WarningDTO]:
        items = self.tree.selectedItems()
        out: List[WarningDTO] = []
        if items:
            for it in items:
                w = it.data(0, Qt.UserRole)
                if isinstance(w, WarningDTO):
                    out.append(w)
        else:
            it = self.tree.currentItem()
            if it:
                w = it.data(0, Qt.UserRole)
                if isinstance(w, WarningDTO):
                    out.append(w)
        return out

    def _ai_clicked(self) -> None:
        ws = self._collect_selected_warnings()
        if not ws:
            QMessageBox.information(self, "Авторозметка", "Не выбраны элементы для разметки.")
            return
        self._ai_run(ws)

    def _ai_clicked_all(self) -> None:
        ws = list(self._filtered) if self._filtered else []
        if not ws:
            QMessageBox.information(self, "Авторозметка", "Нет элементов после фильтрации.")
            return
        self._ai_run(ws)

    def _ai_clicked_whole(self) -> None:
        ws = list(self._all) if self._all else []
        if not ws:
            QMessageBox.information(self, "Авторозметка", "В проекте нет загруженных элементов.")
            return
        self._ai_run(ws)

    def _ai_run(self, ws: list[WarningDTO]) -> None:
        self._toggle_ai_actions(False)

        self._ai_progress = QProgressDialog("Авторозметка…", "Отмена", 0, len(ws), self)
        self._ai_progress.setMinimumDuration(0)
        self._ai_progress.canceled.connect(self._ai_cancel)

        self._ai_thread = QThread(self)
        self._ai_worker = _AIWorker(self.ai, ws, self.code)
        self._ai_worker.moveToThread(self._ai_thread)

        self._ai_thread.started.connect(self._ai_worker.run)
        self._ai_worker.started.connect(lambda total: self._ai_progress.setMaximum(total))
        self._ai_worker.progressed.connect(self._ai_progressed)
        self._ai_worker.error.connect(self._ai_error)
        self._ai_worker.finished.connect(self._ai_finished)

        self._ai_thread.start()

    def _toggle_ai_actions(self, enabled: bool) -> None:
        self.act_ai_selected.setEnabled(enabled)
        self.act_ai_all_filtered.setEnabled(enabled)
        self.act_ai_whole.setEnabled(enabled)
        self.btn_ai.setEnabled(enabled and bool(self.tree.currentItem()
                         and isinstance(self.tree.currentItem().data(0, Qt.UserRole), WarningDTO)))

    @Slot(int, object, object)
    def _ai_progressed(self, i: int, w: WarningDTO, res_obj: Any):
        self._ai_progress.setValue(i)
        res = self._coerce_ai_result(res_obj)
        self._apply_ai_result(w, res)
        self._update_tree_item(w)

        self._ai_marked.add(id(w))

        conf_raw = res.get("confidence", 0)
        try:
            conf_val = float(conf_raw)
        except Exception:
            conf_val = 0.0
        conf_pct = int(round(conf_val * 100)) if conf_val <= 1.0 else int(round(conf_val))
        self.statusBar().showMessage(f"AI: {getattr(w,'status','Не обработано')}, {w.eff_severity()} • {conf_pct}%", 3000)

        self._export_results_auto(final=False)
        self._export_ai_csv_latest()

    @Slot(str)
    def _ai_error(self, msg: str):
        QMessageBox.warning(self, "Авторозметка — ошибка", msg)

    @Slot()
    def _ai_finished(self):
        try:
            self._ai_progress.close()
        except Exception:
            pass
        self._toggle_ai_actions(True)
        if hasattr(self, "_ai_thread"):
            self._ai_thread.quit()
            self._ai_thread.wait(500)
        self._export_results_auto(final=True)
        self._export_ai_csv_snapshot()

    def _ai_cancel(self):
        if hasattr(self, "_ai_worker"):
            self._ai_worker.stop()

    # ---- нормализация результата LLM ----

    def _coerce_ai_result(self, res: Any) -> Dict[str, Any]:
        # поддержка dict / объекта / tuple / прочих значений
        if isinstance(res, dict):
            src = res
        elif isinstance(res, (list, tuple)) and len(res) >= 3:
            # ожидаем (status, severity, comment, [confidence], [label])
            status, severity, comment = res[0], res[1], res[2]
            confidence = res[3] if len(res) > 3 else 0
            label = res[4] if len(res) > 4 else ""
            src = {"status": status, "severity": severity, "comment": comment,
                   "confidence": confidence, "label": label}
        else:
            src = {
                "status": getattr(res, "status", ""),
                "severity": getattr(res, "severity", ""),
                "comment": getattr(res, "comment", ""),
                "confidence": getattr(res, "confidence", 0),
                "label": getattr(res, "label", ""),
            }

        status = str(src.get("status", "")).lower()
        if status not in {"confirmed", "false_positive"}:
            status = "false_positive"
        sev = str(src.get("severity", "")).lower()
        if sev not in {"critical", "medium", "low", "info"}:
            sev = "info"
        try:
            conf = float(src.get("confidence", 0))
        except Exception:
            conf = 0.0
        if conf > 1.0:
            conf = conf / 100.0
        return {
            "status": status,
            "severity": sev,
            "comment": (src.get("comment") or "").strip(),
            "confidence": max(0.0, min(1.0, conf)),
            "label": (src.get("label") or "").strip(),
        }

    def _apply_ai_result(self, w: WarningDTO, res_dict: Dict[str, Any]) -> None:
        status_ru = "Подтверждено" if res_dict["status"] == "confirmed" else "Отклонено"
        w.status = status_ru

        sev = res_dict["severity"]
        if sev not in {"critical", "medium", "low", "info"}:
            sev = "info"
        w.severity_ui = sev

        label = res_dict.get("label") or ""
        comment = res_dict.get("comment") or ""
        w.comment = (f"[{label}] " if label else "") + comment

        if hasattr(w, "ml_confidence"):
            try:
                w.ml_confidence = float(res_dict.get("confidence", 0.0))
            except Exception:
                pass

    def _update_tree_item(self, w: WarningDTO) -> None:
        it = self._warn_item_map.get(id(w)) or self.tree.currentItem()
        if it:
            it.setText(0, self._leaf_caption(w))
            it.setForeground(0, QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827")))
            if self.tree.currentItem() is it:
                self._show_details(w)

    # ---------- Экспорт JSON/CSV ----------

    def _build_export_record(self, w: WarningDTO) -> Dict[str, Any]:
        conf = 0.0
        try:
            conf = float(getattr(w, "ml_confidence", 0.0))
        except Exception:
            conf = 0.0
        return {
            "rule": w.rule_id,
            "severity": w.eff_severity(),
            "file": getattr(w, "file", ""),
            "line": int(getattr(w, "start_line", None) or getattr(w, "line", 0) or 0),
            "message": w.message or "",
            "status": getattr(w, "status", "Не обработано"),
            "comment": getattr(w, "comment", ""),
            "ml_confidence": conf,
            "ml_confidence_pct": int(round(conf * 100)),
        }

    def _collect_export_data(self) -> Dict[str, Any]:
        items = [self._build_export_record(w) for w in self.repo.list_all()]
        return {
            "project_title": self.ed_title.text().strip(),
            "snapshot": self._snapshot_name,
            "source_root": str(self.source_root) if self.source_root else "",
            "total": len(items),
            "items": items,
        }

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка сохранения {path.name}: {e}", 7000)

    def _export_results_auto(self, final: bool) -> Optional[Path]:
        data = self._collect_export_data()
        latest = self.reports_dir / "ai_results_latest.json"
        self._write_json(latest, data)

        saved: Optional[Path] = None
        if final:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            saved = self.reports_dir / f"ai_results_{ts}.json"
            self._write_json(saved, data)
        return saved

    # --- CSV только для AI-размеченных элементов ---

    def _collect_ai_rows(self) -> list[list[str]]:
        rows: list[list[str]] = []
        for w in self.repo.list_all():
            if id(w) not in self._ai_marked:
                continue
            file_ = getattr(w, "file", "") or ""
            line_ = str(int(getattr(w, "start_line", None) or getattr(w, "line", 0) or 0))
            conf = 0.0
            try:
                conf = float(getattr(w, "ml_confidence", 0.0))
            except Exception:
                pass
            rows.append([
                w.rule_id or "",
                w.eff_severity() or "",
                file_,
                line_,
                w.message or "",
                getattr(w, "status", "Не обработано"),
                getattr(w, "comment", ""),
                f"{int(round(conf*100))}",
            ])
        return rows

    def _write_csv(self, path: Path, rows: list[list[str]]) -> None:
        try:
            with path.open("w", encoding="utf-8", newline="") as f:
                wr = csv.writer(f, delimiter=';')
                wr.writerow(["rule","severity","file","line","message","status","comment","confidence_pct"])
                wr.writerows(rows)
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка сохранения CSV: {e}", 7000)

    def _export_ai_csv_latest(self) -> None:
        rows = self._collect_ai_rows()
        latest = self.reports_dir / "ai_results_latest.csv"
        self._write_csv(latest, rows)

    def _export_ai_csv_snapshot(self) -> Optional[Path]:
        rows = self._collect_ai_rows()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = self.reports_dir / f"ai_results_{ts}.csv"
        self._write_csv(path, rows)
        return path

    # единый экспорт (диалог)
    def _open_export_dialog(self):
        def collect_warnings():
            if hasattr(self.repo, "all"):
                return list(self.repo.all())
            for name in ("iter_all", "iter_warnings", "items"):
                if hasattr(self.repo, name):
                    obj = getattr(self.repo, name)
                    data = obj() if callable(obj) else obj
                    return list(data)
            return []

        def collect_pairs():
            """
            Вернуть (warning, ai_result_dict). Если у тебя есть свой словарь
            результатов, замени здесь на свою структуру.
            """
            pairs = []
            warnings = collect_warnings()
            ai_map = getattr(self, "ai_results", {}) or {}
            for w in warnings:
                wid = getattr(w, "id", None) or getattr(w, "rule_id", None)
                a = ai_map.get(wid, {})
                pairs.append((w, a))
            return pairs

        dlg = ExportDialog(self, collect_warnings, collect_pairs, self.reports_dir)
        dlg.exec()
