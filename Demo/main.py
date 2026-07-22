import os
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
    # SOP_FULLSCREEN=1 이면 모니터를 꽉 채운다(시나리오 촬영용, run_scenario.sh 가 설정).
    # showMaximized 를 쓴다 — 진짜 전체화면(showFullScreen)은 제목표시줄이 사라져
    # 창을 닫을 수 없고, 녹화 종료가 GUI 종료에 묶여 있어 위험하다.
    if os.environ.get("SOP_FULLSCREEN", "0") == "1":
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
