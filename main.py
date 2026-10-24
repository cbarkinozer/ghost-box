"""Ghost-box's initial desktop window. Run with: uv run main.py."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Ghost-box")

    window = QMainWindow()
    window.setWindowTitle("Ghost-box")
    window.resize(960, 640)

    empty_state = QLabel("Ghost-box\n\nYour local email companion.")
    empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window.setCentralWidget(empty_state)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
