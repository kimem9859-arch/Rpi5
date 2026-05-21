import sys

from PyQt6.QtWidgets import QApplication
from safety_console import SafetyConsole
from config import BG_PRIMARY, BG_PANEL, TEXT_PRIMARY, BORDER_COLOR, ACCENT


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(f"""
        QMainWindow  {{ background-color: {BG_PRIMARY}; }}
        QWidget      {{ background-color: {BG_PRIMARY}; color: {TEXT_PRIMARY}; font-family: 'Consolas', monospace; }}
        QScrollBar:vertical {{ background: {BG_PANEL}; width: 8px; border: none; }}
        QScrollBar::handle:vertical {{ background: {BORDER_COLOR}; border-radius: 4px; min-height: 20px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QToolTip {{ background-color: {BG_PANEL}; color: {TEXT_PRIMARY}; border: 1px solid {ACCENT}; padding: 4px; }}
    """)
    window = SafetyConsole()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
