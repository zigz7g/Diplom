# -*- coding: utf-8 -*-
from __future__ import annotations

import os, json
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

from core.schema import WarningDTO, SEVERITY_COLORS
from data.repositories.in_memory_repository import InMemoryRepository
from services.code_provider import CodeProvider
from services.use_cases import ImportSarifService
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


def _get_file_str(w: WarningDTO) -> str:
    for attr in ("file_path", "file", "path", "filename", "uri"):
        v = getattr(w, attr, None)
        if v:
            return str(v)
    return ""


def _get_line_int(w: WarningDTO) -> int:
    for attr in ("start_line", "line", "region_start_line", "startLine", "regionStartLine"):
        v = getattr(w, attr, None)
        if v:
            try:
                return int(v)
            except Exception:
                pass
    return 0


# ---------- AI worker ----------

class _AIWorker(QObject):
    started = Signal(int)                               # total
    progressed = Signal(int, object, object)            # i, WarningDTO, ai_result
    error = Signal(str)
    finished = Signal()

    def __init__(self, annotator: AIAnnotator, warnings: List[WarningDTO], code: CodeProvider):
        super().__init__()
        self.annotator = annotator
        self.warnings = list(warnings)
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

                # контекст (полный текст файла — если найдётся)
                p = self.code.find_best(
                    _get_file_str(w),
                    _get_line_int(w),
                    getattr(w, "snippet_text", None) or getattr(w, "snippet", None) or ""
                )
                file_text = ""
                if p and p.exists():
                    try:
                        file_text = _read_text_best_effort(p)
                    except Exception:
                        file_text = ""

                # вызов аннотатора (терпимая сигнатура)
                try:
                    try:
                        res = self.annotator.annotate_one(w)
                    except TypeError:
                        res = self.annotator.annotate_one(
                            rule=getattr(w, "rule_id", None) or getattr(w, "rule", "") or "",
                            level=getattr(w, "level", None) or getattr(w, "severity_ui", "") or "info",
                            file=_get_file_str(w) or "-",
                            line=_get_line_int(w),
                            message=getattr(w, "message", "") or "",
                            snippet=getattr(w, "snippet_text", None) or getattr(w, "snippet", None) or "",
                            file_text=file_text,
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
    """
    Полный просмотр исходника в центре (весь файл),
    подсветка только одной «первичной» строки из SARIF.
    Авторозметка через ЯндексGPT с прогрессом и автосохранением JSON.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVACE Annotator — AI static report assistant")
        self.resize(1600, 900)

        # -------- services / state --------
        self.repo = InMemoryRepository()
        self.import_sarif = ImportSarifService(self.repo)
        self.source_root: Optional[Path] = None
        self.code = CodeProvider(None)

        self.ai_client = YandexGPTClient(
            api_key=os.getenv("YAGPT_API_KEY") or os.getenv("YA_API_KEY") or "",
            folder_id=os.getenv("YAGPT_FOLDER_ID") or os.getenv("YA_FOLDER_ID") or "",
            model_name=os.getenv("YAGPT_MODEL", "yandexgpt")
        )
        self.ai = AIAnnotator(client=self.ai_client)

        # пути для автосохранения
        self.project_root: Path = Path(__file__).resolve().parents[2]  # .../PROJECT/
        self.reports_dir: Path = self.project_root / "reports"
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._snapshot_name: str = "—"

        # ===================== UI =====================
        root = QWidget(self)
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ---- top ----
        top = QHBoxLayout()
        self.ed_title = QLineEdit(placeholderText="Название программы / проекта")
        self.ed_search = QLineEdit(placeholderText="Поиск по правилу / файлу / тексту…")
        self.lab_snapshot = QLabel("Снимок: —")
        self.lab_snapshot.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lab_snapshot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self.ed_title, 2)
        top.addWidget(self.ed_search, 3)
        top.addWidget(self.lab_snapshot, 1)
        layout.addLayout(top)

        # ---- filters ----
        filters = QHBoxLayout()
        self.cb_crit = QCheckBox("Critical"); self.cb_crit.setChecked(True)
        self.cb_med  = QCheckBox("Medium");   self.cb_med.setChecked(True)
        self.cb_low  = QCheckBox("Low");      self.cb_low.setChecked(True)
        self.cb_info = QCheckBox("Info");     self.cb_info.setChecked(True)
        self.cb_group = QCheckBox("Группировать по правилу"); self.cb_group.setChecked(True)
        for cb in (self.cb_crit, self.cb_med, self.cb_low, self.cb_info, self.cb_group):
            filters.addWidget(cb)
        filters.addStretch(1)
        self.btn_reset = QPushButton("Сбросить")
        filters.addWidget(self.btn_reset)
        layout.addLayout(filters)

        # ---- splitter ----
        split = QSplitter(Qt.Horizontal); split.setHandleWidth(4)
        layout.addWidget(split, 1)

        # left: дерево
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        split.addWidget(self.tree)

        # center: полный файл с номерами строк
        from ui.code_editor import CodeEditor
        self.code_view = CodeEditor()
        split.addWidget(self.code_view)

        # right: детали + действия
        right = QWidget()
        r = QFormLayout(right)
        right.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self.lab_rule = QLabel("-");  self.lab_rule.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lab_sev  = QLabel("-")
        self.lab_file = QLabel("-");  self.lab_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lab_line = QLabel("-")
        self.lab_status = QLabel("Не обработано")

        self.ed_message = QTextEdit(); self.ed_message.setReadOnly(True); self.ed_message.setMinimumHeight(70)
        self.ed_comment = QTextEdit(); self.ed_comment.setReadOnly(True); self.ed_comment.setMinimumHeight(90)

        r.addRow(QLabel("Правило:"), self.lab_rule)
        r.addRow(QLabel("Уровень:"), self.lab_sev)
        r.addRow(QLabel("Файл:"),   self.lab_file)
        r.addRow(QLabel("Строка:"), self.lab_line)
        r.addRow(QLabel("Статус:"), self.lab_status)
        r.addRow(QLabel("Сообщение:"), self.ed_message)
        r.addRow(QLabel("Комментарий:"), self.ed_comment)

        row = QHBoxLayout()
        self.btn_ai = QPushButton("Авторазметка (ЯндексGPT)"); self.btn_ai.setEnabled(False)
        self.btn_annotate = QPushButton("Разметить…");         self.btn_annotate.setEnabled(False)
        row.addWidget(self.btn_ai); row.addWidget(self.btn_annotate)
        r.addRow(row)

        split.addWidget(right)
        split.setSizes([420, 820, 320])

        # ---- menu ----
        menu_file = self.menuBar().addMenu("Файл")
        self.act_open_sarif = QAction("Открыть SARIF…", self)
        self.act_bind_src   = QAction("Привязать исходники…", self)
        self.act_exit       = QAction("Выход", self)
        menu_file.addAction(self.act_open_sarif)
        menu_file.addAction(self.act_bind_src)
        menu_file.addSeparator()
        menu_file.addAction(self.act_exit)

        # ---- signals ----
        self.tree.itemSelectionChanged.connect(self._on_item_changed)
        self.ed_search.textChanged.connect(lambda *_: self._reload_filtered())
        for cb in (self.cb_crit, self.cb_med, self.cb_low, self.cb_info, self.cb_group):
            cb.stateChanged.connect(lambda *_: self._reload_filtered())

        self.btn_reset.clicked.connect(self._reset_filters)
        self.btn_annotate.clicked.connect(self._annotate_current)
        self.btn_ai.clicked.connect(self._ai_clicked)
        self.act_open_sarif.triggered.connect(self._open_sarif)
        self.act_bind_src.triggered.connect(self._pick_source_root)
        self.act_exit.triggered.connect(self.close)

        # ---- init ----
        self._all: List[WarningDTO] = []
        self._filtered: List[WarningDTO] = []
        self._warn_item_map: Dict[int, QTreeWidgetItem] = {}
        self._reload_filtered()
        self.statusBar().showMessage("Готово")

    # ===================== actions =====================

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
                    "Привязать каталог исходников для просмотра полного файла?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
                ) == QMessageBox.Yes:
                    self._pick_source_root()
        except Exception as e:
            QMessageBox.critical(self, "SARIF", f"Ошибка импорта:\n{e}\n\n{format_exc()}")

    def _pick_source_root(self) -> None:
        dir_ = QFileDialog.getExistingDirectory(self, "Выбрать корень исходников", "")
        if not dir_:
            return
        self.source_root = Path(dir_)
        self.code.set_root(self.source_root)
        QMessageBox.information(self, "Исходники", f"Привязан каталог исходников:\n{self.source_root}")

    # ===================== list render =====================

    def _reload_filtered(self) -> None:
        text = self.ed_search.text().strip().lower()
        use_groups = self.cb_group.isChecked()
        enabled = {
            "critical": self.cb_crit.isChecked(),
            "medium":   self.cb_med.isChecked(),
            "low":      self.cb_low.isChecked(),
            "info":     self.cb_info.isChecked(),
        }

        self.tree.clear()
        self._warn_item_map.clear()
        items: List[WarningDTO] = []
        for w in self._all:
            if not enabled.get((w.eff_severity() or "medium").lower(), True):
                continue
            cap = " ".join([w.rule_id or "", _get_file_str(w), w.message or "", (w.comment or "")]).lower()
            if text and text not in cap:
                continue
            items.append(w)
        self._filtered = items

        if use_groups:
            by_rule: Dict[str, List[WarningDTO]] = {}
            for w in items:
                by_rule.setdefault(w.rule_id or "(no-rule)", []).append(w)
            for rule, warnings in sorted(by_rule.items(), key=lambda kv: kv[0].lower()):
                head = QTreeWidgetItem([f"{rule} — {len(warnings)}"])
                head.setFirstColumnSpanned(True)
                head.setData(0, Qt.UserRole, None)
                self.tree.addTopLevelItem(head)
                for w in warnings:
                    leaf = QTreeWidgetItem([self._leaf_caption(w)])
                    leaf.setData(0, Qt.UserRole, w)
                    leaf.setForeground(0, QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827")))
                    head.addChild(leaf)
                    self._warn_item_map[id(w)] = leaf
                head.setExpanded(True)
        else:
            for w in items:
                leaf = QTreeWidgetItem([self._leaf_caption(w)])
                leaf.setData(0, Qt.UserRole, w)
                leaf.setForeground(0, QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827")))
                self.tree.addTopLevelItem(leaf)
                self._warn_item_map[id(w)] = leaf

        self.btn_annotate.setEnabled(False); self.btn_ai.setEnabled(False)
        if self.tree.topLevelItemCount() > 0:
            first = self.tree.topLevelItem(0)
            sel = first.child(0) if first and first.childCount() > 0 else first
            self.tree.setCurrentItem(sel)

    def _leaf_caption(self, w: WarningDTO) -> str:
        mark = ""
        if w.status == "Подтверждено": mark = "  ✔"
        elif w.status == "Отклонено":   mark = "  ✖"
        file_name = Path(_get_file_str(w)).name or "(файл не указан)"
        line_show = _get_line_int(w) or "-"
        return f"[{w.eff_severity()}] {file_name} : {w.rule_id} : {line_show}{mark}"

    # ===================== selection/details =====================

    def _on_item_changed(self) -> None:
        item = self.tree.currentItem()
        if not item:
            self._clear_details(); return
        w = item.data(0, Qt.UserRole)
        if not isinstance(w, WarningDTO):
            self._clear_details(); return

        self._show_details(w)
        try:
            self._show_code(w)
        finally:
            self.btn_annotate.setEnabled(True)
            self.btn_ai.setEnabled(True)

    def _clear_details(self) -> None:
        self.lab_rule.setText("-"); self.lab_sev.setText("-")
        self.lab_file.setText("-"); self.lab_line.setText("-")
        self.lab_status.setText("Не обработано")
        self.ed_message.setPlainText("")
        self.ed_comment.setPlainText("")
        self.code_view.setPlainText("")
        self.code_view.clear_highlight()

    def _show_details(self, w: WarningDTO) -> None:
        self.lab_rule.setText(w.rule_id or "-")
        self.lab_sev.setText(w.eff_severity() or "-")
        self.lab_file.setText(_get_file_str(w) or "-")
        self.lab_line.setText(str(_get_line_int(w) or "-"))
        self.lab_status.setText(getattr(w, "status", "") or "Не обработано")
        self.ed_message.setPlainText(w.message or "")
        self.ed_comment.setPlainText(w.comment or "")

    # ---------- полный файл + подсветка одной строки ----------

    def _resolve_fs_path(self, w: WarningDTO) -> Optional[Path]:
        if self.source_root is None:
            return None
        file_hint = _get_file_str(w)
        line = _get_line_int(w)
        snippet = getattr(w, "snippet_text", None) or getattr(w, "snippet", None) or ""
        return self.code.find_best(file_hint, line, snippet)

    def _show_code(self, w: WarningDTO) -> None:
        p = self._resolve_fs_path(w)
        if not p or not p.exists():
            self.code_view.setPlainText("")
            self.code_view.clear_highlight()
            return

        text = self.code.read_text(p)
        self.code_view.setPlainText(text)
        self.code_view.clear_highlight()

        line = _get_line_int(w)
        max_line = self.code_view.document().blockCount()
        if line < 1 or line > max_line:
            snippet = getattr(w, "snippet_text", None) or getattr(w, "snippet", None) or ""
            line = self._find_line_by_snippet(text, snippet)

        if 1 <= line <= max_line:
            self.code_view.highlight_lines([line])
            self.code_view.scroll_to_line(line)

    # --- helpers: поиск строки по сниппету ---

    def _needles_from_snippet(self, snippet: str) -> list[str]:
        if not snippet:
            return []
        lines = [ln.strip() for ln in snippet.splitlines() if ln.strip()]
        lines.sort(key=len, reverse=True)
        return [ln for ln in lines if len(ln) >= 6]

    def _find_line_by_snippet(self, file_text: str, snippet: str) -> int:
        if not file_text or not snippet:
            return 0
        needles = self._needles_from_snippet(snippet)
        if not needles:
            return 0
        for nd in needles:
            idx = file_text.find(nd)
            if idx != -1:
                return file_text[:idx].count("\n") + 1

        def squash(s: str) -> str:
            return " ".join(s.replace("\r", "").split())

        ft = squash(file_text)
        for nd in needles:
            idx = ft.find(squash(nd))
            if idx != -1:
                token = nd[:24]
                rough = file_text.find(token)
                if rough != -1:
                    return file_text[:rough].count("\n") + 1
        return 0

    # ===================== ручная разметка =====================

    def _annotate_current(self) -> None:
        item = self.tree.currentItem()
        if not item:
            return
        w = item.data(0, Qt.UserRole)
        if not isinstance(w, WarningDTO):
            return

        from ui.annotate_dialog import AnnotateDialog
        dlg = AnnotateDialog(self, w.status or "Не обработано", w.eff_severity(), w.comment or "")
        if dlg.exec() == QDialog.Accepted:
            status, sev, comment = dlg.chosen()
            w.status = status
            w.severity_ui = sev
            w.comment = comment

            self._show_details(w)
            item.setText(0, self._leaf_caption(w))
            item.setForeground(0, QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827")))

    # ===================== AI разметка =====================

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

    def _coerce_ai_result(self, res: Any) -> Dict[str, Any]:
        if isinstance(res, dict):
            return {
                "status": res.get("status", ""),
                "severity": res.get("severity", ""),
                "comment": res.get("comment", ""),
                "confidence": res.get("confidence", 0),
                "label": res.get("label", ""),
            }
        return {
            "status": getattr(res, "status", ""),
            "severity": getattr(res, "severity", ""),
            "comment": getattr(res, "comment", ""),
            "confidence": getattr(res, "confidence", 0),
            "label": getattr(res, "label", ""),
        }

    def _apply_ai_result(self, w: WarningDTO, res_dict: Dict[str, Any]) -> None:
        status_map = {
            "confirmed": "Подтверждено",
            "false_positive": "Ложноположительное",
            "insufficient_evidence": "Не хватает контекста",
        }
        w.status = status_map.get(str(res_dict.get("status", "")).lower(), "Не обработано")

        sev = str(res_dict.get("severity", "")).lower()
        if sev not in {"critical", "medium", "low", "info"}:
            sev = "info"
        w.severity_ui = sev

        label = (res_dict.get("label") or "").strip()
        comment = (res_dict.get("comment") or "").strip()
        w.comment = (f"[{label}] " if label else "") + comment

        # нормализуем confidence (0..1 или 0..100)
        conf_raw = res_dict.get("confidence", 0)
        try:
            conf_val = float(conf_raw)
        except Exception:
            conf_val = 0.0
        conf_ratio = conf_val / 100.0 if conf_val > 1.0 else conf_val

        if hasattr(w, "ml_confidence"):
            try:
                w.ml_confidence = float(conf_ratio)
            except Exception:
                pass

    def _update_tree_item(self, w: WarningDTO) -> None:
        it = self._warn_item_map.get(id(w)) or self.tree.currentItem()
        if it:
            it.setText(0, self._leaf_caption(w))
            it.setForeground(0, QColor(SEVERITY_COLORS.get(w.eff_severity(), "#111827")))
            if self.tree.currentItem() is it:
                self._show_details(w)

    # ---- экспорт JSON ----

    def _build_export_record(self, w: WarningDTO) -> Dict[str, Any]:
        conf = 0.0
        try:
            conf = float(getattr(w, "ml_confidence", 0.0))
        except Exception:
            conf = 0.0
        return {
            "rule": w.rule_id,
            "severity": w.eff_severity(),
            "file": _get_file_str(w),
            "line": _get_line_int(w),
            "message": w.message or "",
            "status": getattr(w, "status", "Не обработано"),
            "comment": getattr(w, "comment", ""),
            "ml_confidence": conf,                       # 0..1
            "ml_confidence_pct": int(round(conf * 100))  # 0..100
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
        # актуальный снепшот всегда пишем сюда
        latest = self.reports_dir / "ai_results_latest.json"
        self._write_json(latest, data)

        saved: Optional[Path] = None
        if final:
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            saved = self.reports_dir / f"ai_results_{ts}.json"
            self._write_json(saved, data)
        return saved

    # ---- AI: запускаем/обновляем/завершаем ----

    def _ai_clicked(self) -> None:
        ws = self._collect_selected_warnings()
        if not ws:
            QMessageBox.information(self, "Авторозметка", "Не выбраны элементы для разметки.")
            return

        self.btn_ai.setEnabled(False)
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

    @Slot(int, object, object)
    def _ai_progressed(self, i: int, w: WarningDTO, res_obj: Any):
        self._ai_progress.setValue(i)
        res = self._coerce_ai_result(res_obj)
        self._apply_ai_result(w, res)
        self._update_tree_item(w)

        # процент уверенности в статус-бар
        conf_raw = res.get("confidence", 0)
        try:
            conf_val = float(conf_raw)
        except Exception:
            conf_val = 0.0
        conf_pct = int(round(conf_val * 100)) if conf_val <= 1.0 else int(round(conf_val))
        self.statusBar().showMessage(f"AI: {w.status}, {w.eff_severity()} • {conf_pct}%", 3000)

        # автообновление "latest"
        self._export_results_auto(final=False)

    @Slot(str)
    def _ai_error(self, msg: str):
        QMessageBox.warning(self, "Авторозметка — ошибка", msg)

    @Slot()
    def _ai_finished(self):
        # финальный снимок (даже если часть была отменена — что успели, то и сохраним)
        saved = self._export_results_auto(final=True)

        try:
            self._ai_progress.close()
        except Exception:
            pass

        self.btn_ai.setEnabled(True)
        if hasattr(self, "_ai_thread"):
            self._ai_thread.quit()
            self._ai_thread.wait(500)

        if saved:
            self.statusBar().showMessage(f"Экспортировано: {saved.name}", 6000)

    def _ai_cancel(self):
        if hasattr(self, "_ai_worker"):
            self._ai_worker.stop()
        # не закрываем прогресс немедленно — пусть воркер корректно дойдёт до finished,
        # тогда _ai_finished сохранит финальный JSON и аккуратно закроет диалог.
