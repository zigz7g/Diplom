from PySide6.QtWidgets import QApplication
import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Cyber AI")
    win = MainWindow()
    win.resize(1100, 720)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
