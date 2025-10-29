from __future__ import annotations
import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

QSS = """
* { font-family: 'Inter', 'Segoe UI', Arial; font-size: 12px; }
QMainWindow { background: #f7f8fa; }
QLineEdit, QTextEdit, QPlainTextEdit {
  background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 6px 8px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
  border: 1px solid #60a5fa; background: #ffffff;
}
QPushButton {
  background: #2563eb; color: white; border: none; border-radius: 10px; padding: 8px 14px;
}
QPushButton:hover { background: #1e40af; }
QPushButton:disabled { background: #a7b0c0; color: #f0f3f7; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
  width: 18px; height: 18px; border-radius: 5px; border: 1px solid #c7d0dd; background: #fff;
}
QCheckBox::indicator:checked { background: #2563eb; border: 1px solid #2563eb; }
QSplitter::handle { background: #e5e7eb; width: 4px; }
QTreeWidget {
  background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 6px;
}
QTreeView::item { padding: 4px 6px; border-radius: 6px; }
QTreeView::item:selected { background: #e0edff; color: #0f172a; }
QLabel#smallMuted { color: #6b7280; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
