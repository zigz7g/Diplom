import sys, os
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SVACE Annotator (Core)")
    win = MainWindow()
    win.resize(1200, 720)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
