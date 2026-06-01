from __future__ import annotations

import os
import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .updater import Updater

DEFAULT_VERSION = "v0.0.0"
DEFAULT_REPO_OWNER = "q09009"
DEFAULT_REPO_NAME = "qt-updater"


def parse_current_version(argv: list[str]) -> str:
    for i in range(1, len(argv)):
        if argv[i] == "-v" and i + 1 < len(argv):
            return argv[i + 1]
    return DEFAULT_VERSION


class UpdaterWindow(QMainWindow):
    def __init__(self, updater: Updater) -> None:
        super().__init__()
        self.updater = updater

        self.setWindowTitle("Updater")
        self.resize(620, 440)

        central = QWidget(self)
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(18)

        title = QLabel("System Update in Progress")
        title.setStyleSheet("font-size: 22px; font-weight: 700; color: #0f172a;")
        title.setWordWrap(True)
        layout.addWidget(title)

        self.status_label = QLabel("Checking update status...")
        self.status_label.setStyleSheet("font-size: 16px; color: #0f172a;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(24)
        layout.addWidget(self.progress_bar)

        self.percent_label = QLabel("0%")
        self.percent_label.setStyleSheet("font-size: 34px; font-weight: 700; color: #0f172a;")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.percent_label)

        self.log_area = QPlainTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setStyleSheet("font-size: 14px; color: #0f172a; background: #ffffff;")
        layout.addWidget(self.log_area)

        updater.status_message_changed.connect(self.on_status_message_changed)
        updater.status_log_changed.connect(self.on_status_log_changed)
        updater.progress_changed.connect(self.on_progress_changed)

    def on_status_message_changed(self, message: str) -> None:
        self.status_label.setText(message or "Checking update status...")

    def on_status_log_changed(self, log_text: str) -> None:
        self.log_area.setPlainText(log_text)

    def on_progress_changed(self, value: int) -> None:
        self.progress_bar.setValue(value)
        self.percent_label.setText(f"{value}%")


def main() -> int:
    app = QApplication(sys.argv)

    current_version = parse_current_version(sys.argv)
    repo_owner = os.getenv("UPDATER_REPO_OWNER", DEFAULT_REPO_OWNER)
    repo_name = os.getenv("UPDATER_REPO_NAME", DEFAULT_REPO_NAME)

    updater = Updater(current_version, repo_owner, repo_name)
    window = UpdaterWindow(updater)
    window.show()

    updater.finished.connect(app.quit)
    QTimer.singleShot(0, updater.start_update)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
