# src/ui/main_window.py
from pathlib import Path
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QListWidget, QListWidgetItem, QPlainTextEdit, QFileDialog, QMessageBox,
    QLineEdit, QLabel, QPushButton, QCheckBox, QGridLayout, QFrame,
    QStatusBar, QToolBar
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
import json
# Бизнес-слой
from data.repositories.in_memory_repository import InMemoryRepository
from data.importers.sample_json_importer import SampleJsonImporter
from services.use_cases import ImportWarningsService
from data.importers.pdf_report_importer import PdfReportImporter
from services.export_service import export_warnings
from services.code_provider import SimpleCodeProvider
from data.importers.sarif_report_importer import SarifReportImporter


# Цвета серьёзности (только для подсветки текста в списке)
SEV_COLOR = {
    "error": QColor(220, 20, 60),      # crimson
    "warning": QColor(255, 140, 0),    # dark orange
    "note": QColor(70, 130, 180),      # steel blue
}

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVACE Annotator")
        self.resize(1200, 800)

        # === Состояние ===
        self.current_program_name = ""
        self.repo = InMemoryRepository()
        self.importer = SampleJsonImporter()
        self.code = SimpleCodeProvider()
        self.import_uc = ImportWarningsService(self.importer, self.repo)
        self._warnings = []

        # === Верхняя панель ===
        header = QFrame()
        header.setObjectName("header")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 6, 12, 6)

        lbl_proj = QLabel("Проект:")
        lbl_proj.setObjectName("projectLabel")
        self.program_name = QLineEdit()
        self.program_name.setObjectName("programName")
        self.program_name.setPlaceholderText("Название программы (как в Solar appScreener: Project / Application)")
        self.program_name.textChanged.connect(self._on_program_name)

        self.snapshot_info = QLabel("Снапшот: не загружен")
        self.snapshot_info.setObjectName("snapshotInfo")
        self.snapshot_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h.addWidget(lbl_proj)
        h.addWidget(self.program_name, 2)
        h.addWidget(self.snapshot_info, 1)

        # === Левая панель: фильтры + список ===
        left = QWidget()
        left.setObjectName("leftPanel")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(6, 6, 6, 6)

        filters = QGroupBox("Фильтры")
        filters.setObjectName("filtersGroup")
        g = QGridLayout(filters)
        g.setSpacing(6)

        self.filter_search = QLineEdit()
        self.filter_search.setObjectName("filterSearch")
        self.filter_search.setPlaceholderText("Поиск по правилу / файлу / тексту…")

        self.cb_error = QCheckBox("Error")
        self.cb_error.setObjectName("cbError")
        self.cb_error.setChecked(True)

        self.cb_warning = QCheckBox("Warning")
        self.cb_warning.setObjectName("cbWarning")
        self.cb_warning.setChecked(True)

        self.cb_note = QCheckBox("Note")
        self.cb_note.setObjectName("cbNote")
        self.cb_note.setChecked(True)

        btn_clear = QPushButton("Сбросить")
        btn_clear.setObjectName("btnClearFilters")

        g.addWidget(self.filter_search, 0, 0, 1, 3)
        g.addWidget(self.cb_error, 1, 0)
        g.addWidget(self.cb_warning, 1, 1)
        g.addWidget(self.cb_note, 1, 2)
        g.addWidget(btn_clear, 2, 2, alignment=Qt.AlignRight)

        self.findings = QListWidget()
        self.findings.setObjectName("findingsList")
        self.findings.currentItemChanged.connect(self._on_item_changed)

        left_l.addWidget(filters)
        left_l.addWidget(self.findings, 1)

        self.filter_search.textChanged.connect(self._apply_filter)
        self.cb_error.toggled.connect(self._apply_filter)
        self.cb_warning.toggled.connect(self._apply_filter)
        self.cb_note.toggled.connect(self._apply_filter)
        btn_clear.clicked.connect(self._clear_filters)

        # === Центр: код ===
        center = QWidget()
        center.setObjectName("centerPanel")
        center_l = QVBoxLayout(center)
        center_l.setContentsMargins(6, 6, 6, 6)

        self.code_view = QPlainTextEdit()
        self.code_view.setObjectName("codeView")
        self.code_view.setReadOnly(True)
        center_l.addWidget(self.code_view, 1)

        # === Правая панель: детали + AI ===
        right = QWidget()
        right.setObjectName("rightPanel")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(6, 6, 6, 6)

        box_details = QGroupBox("Детали")
        box_details.setObjectName("detailsGroup")
        det = QGridLayout(box_details)
        det.setSpacing(6)

        self.lbl_rule = QLabel("-")
        self.lbl_sev = QLabel("-")
        self.lbl_file = QLabel("-")
        self.lbl_line = QLabel("-")

        det.addWidget(QLabel("Правило:"), 0, 0)
        det.addWidget(self.lbl_rule, 0, 1)
        det.addWidget(QLabel("Уровень:"), 1, 0)
        det.addWidget(self.lbl_sev, 1, 1)
        det.addWidget(QLabel("Файл:"), 2, 0)
        det.addWidget(self.lbl_file, 2, 1)
        det.addWidget(QLabel("Строка:"), 3, 0)
        det.addWidget(self.lbl_line, 3, 1)

        box_msg = QGroupBox("Сообщение анализатора")
        box_msg.setObjectName("messageGroup")
        ml = QVBoxLayout(box_msg)
        self.msg_view = QPlainTextEdit()
        self.msg_view.setObjectName("messageView")
        self.msg_view.setReadOnly(True)
        self.msg_view.setMaximumHeight(140)
        ml.addWidget(self.msg_view)

        box_ai = QGroupBox("AI-разметка (скоро)")
        box_ai.setObjectName("aiGroup")
        ail = QVBoxLayout(box_ai)
        self.ai_placeholder = QLabel(
            "Заглушка: подключим локальную LLM позже. "
            "Здесь появятся: краткое описание, root cause, fix-suggestion, риск."
        )
        self.ai_placeholder.setObjectName("aiPlaceholder")
        self.ai_placeholder.setWordWrap(True)
        ail.addWidget(self.ai_placeholder)

        right_l.addWidget(box_details)
        right_l.addWidget(box_msg)
        right_l.addWidget(box_ai, 1)

        # === Сплиттер и центральный виджет ===
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setStretchFactor(2, 3)

        central = QWidget()
        central.setObjectName("centralWidget")
        root_l = QVBoxLayout(central)
        root_l.setContentsMargins(0, 0, 0, 0)
        root_l.setSpacing(0)
        root_l.addWidget(header)
        root_l.addWidget(splitter, 1)
        self.setCentralWidget(central)

        # === Меню и тулбар ===
        self._build_menus()
        self._build_toolbar()

        # === Статус-бар ===
        sb = QStatusBar()
        sb.setObjectName("statusBar")
        self.lbl_count = QLabel("0 найдено")
        self.lbl_count.setObjectName("statusLabel")
        sb.addPermanentWidget(self.lbl_count)
        self.setStatusBar(sb)

        # === Загрузка стиля ===
        self._load_stylesheet()

    def _load_stylesheet(self):
        """Загружает QSS из файла."""
        paths_to_try = [
            Path(__file__).parent / "styles.qss",
            Path("src/ui/styles.qss"),
            Path("styles.qss")
        ]
        for path in paths_to_try:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        self.setStyleSheet(f.read())
                    return
                except Exception as e:
                    print(f"Не удалось загрузить стиль из {path}: {e}")
        print("Файл стиля styles.qss не найден. Используется системный стиль.")

    def _build_menus(self):
        m_file = self.menuBar().addMenu("Файл")
        act_new = QAction("Новый проект…", self); act_new.triggered.connect(self._todo)
        act_open_sarif = QAction("Открыть SARIF отчёт…", self); act_open_sarif.triggered.connect(self._open_sarif)  # Новый пункт
        act_export_csv = QAction("Экспорт CSV/XLSX…", self); act_export_csv.triggered.connect(self._export)
        act_exit = QAction("Выход", self); act_exit.triggered.connect(self.close)
        m_file.addAction(act_new)
        m_file.addAction(act_open_sarif); m_file.addSeparator()  # Добавляем пункт
        m_file.addAction(act_export_csv); m_file.addSeparator()
        m_file.addAction(act_exit)

        m_an = self.menuBar().addMenu("Анализ")
        m_an.addAction(QAction("Запустить аннотацию AI (локально)", self, enabled=False))
        m_an.addAction(QAction("Пересчитать риск", self, enabled=False))
        m_an.addAction(QAction("Пометить как ложноположительное", self, enabled=False))

        m_view = self.menuBar().addMenu("Вид")
        m_view.addAction(QAction("Тёмная тема", self, enabled=False))
        m_view.addAction(QAction("Светлая тема", self, enabled=False))

        m_help = self.menuBar().addMenu("Справка")
        m_help.addAction(QAction("Горячие клавиши", self, enabled=False))
        act_about = QAction("О программе", self); act_about.triggered.connect(self._about)
        m_help.addAction(act_about)

        m_dev = self.menuBar().addMenu("Dev")
        act_dev_import = QAction("Импорт sample JSON…", self); act_dev_import.triggered.connect(self._import_sample_json)
        m_dev.addAction(act_dev_import)

    def _build_toolbar(self):
        tb = QToolBar("Основные действия")
        self.addToolBar(tb)
        b_new = QAction("Новый проект", self);
        b_new.triggered.connect(self._todo)
        b_open = QAction("Открыть SARIF", self);
        b_open.triggered.connect(self._open_sarif)  # Новый пункт
        b_export = QAction("Экспорт", self);
        b_export.triggered.connect(self._export)
        b_ai = QAction("Аннотация AI", self);
        b_ai.setEnabled(False)
        tb.addAction(b_new);
        tb.addAction(b_open);
        tb.addSeparator()
        tb.addAction(b_export);
        tb.addSeparator();
        tb.addAction(b_ai)

    def _on_program_name(self, text: str):
        self.current_program_name = text.strip()
        title = "SVACE Annotator"
        if self.current_program_name:
            title += f" — {self.current_program_name}"
        self.setWindowTitle(title)

    def _todo(self):
        QMessageBox.information(self, "Недоступно", "Функция будет реализована позже.")

    def _about(self):
        QMessageBox.about(
            self,
            "О программе",
            "SVACE Annotator — офлайн-приложение для разметки результатов статического анализа.\n"
            "GUI вдохновлён Solar appScreener. Ввод: PDF-отчёт (позже), экспорт: CSV/XLSX (позже).\n"
            "Версия MVP: 0.1"
        )

    def _open_sarif(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть SARIF отчёт", "", "SARIF (*.sarif);;JSON (*.json)")
        if not path:
            return
        try:
            importer = SarifReportImporter()  # Создаем импортёр SARIF
            items = importer.load(path)  # Загружаем уязвимости из SARIF файла
            self.repo.clear()
            self.repo.add_many(items)
            self._warnings = self.repo.list_all()  # Получаем все уязвимости
            self._populate_list()  # Обновляем список уязвимостей
            self.snapshot_info.setText(f"Снапшот: {Path(path).name}")  # Обновляем информацию о файле
            QMessageBox.information(self, "Импорт SARIF", f"Загружено записей: {len(items)}")  # Показываем уведомление
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта SARIF", str(e))

    def _import_sample_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите пример JSON", "", "JSON (*.json)")
        if not path:
            return
        try:
            n = self.import_uc.run(path)
            self._warnings = self.repo.list_all()
            self._populate_list()
            self.snapshot_info.setText(f"Снапшот: {Path(path).name} (sample)")
            self.filter_search.setFocus()
            QMessageBox.information(self, "Импорт", f"Загружено записей: {n}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта JSON", str(e))

    def _populate_list(self):
        self.findings.clear()
        for w in self._warnings:
            item = QListWidgetItem(self._format_item(w))
            item.setData(Qt.UserRole, w)
            col = SEV_COLOR.get((w.severity or "").lower())
            if col:
                item.setForeground(col)
            self.findings.addItem(item)
        self._update_count_label()

    def _format_item(self, w):
        return f"[{w.severity}] {w.rule_id} — {w.file_path}:{w.start_line}"

    def _apply_filter(self):
        q = self.filter_search.text().strip().lower()
        show_error = self.cb_error.isChecked()
        show_warning = self.cb_warning.isChecked()
        show_note = self.cb_note.isChecked()

        self.findings.clear()
        for w in self._warnings:
            sev = (w.severity or "").lower()
            if sev == "error" and not show_error: continue
            if sev == "warning" and not show_warning: continue
            if sev == "note" and not show_note: continue

            s = f"{w.rule_id} {w.severity} {w.message} {w.file_path}".lower()
            if q and q not in s:
                continue
            item = QListWidgetItem(self._format_item(w))
            item.setData(Qt.UserRole, w)
            col = SEV_COLOR.get(sev)
            if col:
                item.setForeground(col)
            self.findings.addItem(item)
        self._update_count_label()

    def _clear_filters(self):
        self.filter_search.clear()
        self.cb_error.setChecked(True)
        self.cb_warning.setChecked(True)
        self.cb_note.setChecked(True)
        self._apply_filter()

    def _on_item_changed(self, current_item, _):
        if not current_item:
            return

        vuln = current_item.data(Qt.UserRole)
        self.lbl_rule.setText(vuln.rule_id)
        self.lbl_sev.setText(vuln.severity)
        self.lbl_file.setText(vuln.file_path)
        self.lbl_line.setText(str(vuln.start_line))
        self.msg_view.setPlainText(vuln.message)  # Сообщение анализатора

        # Получаем только строки кода
        code_snippet = self._get_code_snippet(vuln.raw)  # Извлекаем строки кода

        if code_snippet:
            self.code_view.setPlainText(code_snippet)  # Отображаем только фрагмент кода
        else:
            self.code_view.setPlainText(f"Фрагмент кода не найден для: {vuln.file_path}:{vuln.start_line}")

    def _get_code_snippet(self, raw_data: str) -> str:
        """Извлекаем фрагмент кода из SARIF данных (snippet или location)."""
        try:
            # Пробуем разобрать JSON-строку
            data = json.loads(raw_data)

            # Если есть фрагмент кода в 'snippet', извлекаем его
            snippet = data.get("message", {}).get("text", "")
            if snippet:
                return snippet.strip()

            # Если snippet нет, пытаемся извлечь код из 'locations' (если есть)
            locations = data.get("locations", [])
            if locations:
                # Получаем путь и строку для извлечения контекста кода
                file_path = locations[0].get("physicalLocation", {}).get("fileLocation", {}).get("uri", "")
                line = locations[0].get("physicalLocation", {}).get("region", {}).get("startLine", 0)
                if file_path and line:
                    # Извлекаем несколько строк вокруг уязвимости
                    return self.code.get_context(file_path, line, 5)  # Возвращаем 5 строк (до и после)
            return None
        except Exception as e:
            return f"Ошибка при извлечении фрагмента: {str(e)}"

    def _update_count_label(self):
        shown = self.findings.count()
        total = len(self._warnings)
        self.lbl_count.setText(f"Отобрано: {shown} / всего: {total}")

    def _export(self):
        if not self._warnings:
            QMessageBox.information(self, "Экспорт", "Нет данных для экспорта.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", "", "Excel (*.xlsx);;CSV (*.csv)"
        )
        if not path:
            return
        try:
            out = export_warnings(self._warnings, path)
            QMessageBox.information(self, "Экспорт", f"Сохранено: {out}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка экспорта", str(e))