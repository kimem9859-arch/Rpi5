import os
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
import config
from safety_console import SafetyConsole
from config import BG_PRIMARY, BG_PANEL, TEXT_PRIMARY, BORDER_COLOR, ACCENT, UI_FONT_FAMILY


def main():
    app = QApplication(sys.argv)
    # 🔴 폰트 이름은 config 가 단일 정본이다 — 여기 'Consolas' 가 박혀 있어서
    #    앱 전역 기본 글꼴이 조용히 중국어 폰트로 폴백되고 있었다(2026-08-03 발견).
    app.setStyleSheet(f"""
        QMainWindow  {{ background-color: {BG_PRIMARY}; }}
        QWidget      {{ background-color: {BG_PRIMARY}; color: {TEXT_PRIMARY}; font-family: '{UI_FONT_FAMILY}', sans-serif; }}
        QScrollBar:vertical {{ background: {BG_PANEL}; width: 8px; border: none; }}
        QScrollBar::handle:vertical {{ background: {BORDER_COLOR}; border-radius: 4px; min-height: 20px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QToolTip {{ background-color: {BG_PANEL}; color: {TEXT_PRIMARY}; border: 1px solid {ACCENT}; padding: 4px; }}
    """)
    window = SafetyConsole()
    # SOP_FULLSCREEN=1 이면 모니터를 꽉 채운다(시나리오 촬영용, run_scenario.sh 가 설정).
    # showMaximized 를 쓴다 — 진짜 전체화면(showFullScreen)은 제목표시줄이 사라져
    # 창을 닫을 수 없고, 녹화 종료가 GUI 종료에 묶여 있어 위험하다.
    # 촬영 모드는 창을 16:9 로 고정한다 — 잘라낼 좌표가 딱 떨어지고 편집 규격 그대로다.
    # 🔴 최대화·전체화면을 쓰지 않는다. 최대화는 비율이 어중간하고, 전체화면은
    #    제목표시줄이 없어져 창을 닫을 수 없다(녹화 종료가 GUI 종료에 묶여 있다).
    if config.DEMO_CAPTURE:
        # 🔴 잘라낼 사각형 안에 다른 창이 겹치면 **그 창이 그대로 찍힌다.**
        #    2026-09-03 검증에서 실제로 터미널이 찍혔다 — raise_() 만으로는 부족하다.
        from PyQt6.QtCore import Qt
        window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        window.resize(*config.DEMO_CAPTURE_SIZE)
        window.show()
        # 🔴 move 는 show 뒤여야 한다 — 앞에 두면 창 관리자가 무시하고 제멋대로
        #    놓는다(2026-09-03: 항상-위 를 켠 뒤 창이 614,604 로 가서 화면 캡처가
        #    'outside the screen size' 로 즉시 죽었다).
        window.move(0, 40)
        # 🔴 촬영 모드에서만 SIGINT/SIGTERM 을 창 닫기로 바꾼다.
        #    없으면 런처에서 Ctrl+C 를 누르거나 프로세스를 종료했을 때 closeEvent 가
        #    안 돌아 촬영정보.txt 가 안 남고 ffmpeg 정리가 늦는다.
        #    타이머 한 방은 파이썬이 신호를 처리할 틈을 주기 위한 것이다(Qt 이벤트 루프
        #    안에서는 파이썬 핸들러가 안 불린다).
        import signal
        signal.signal(signal.SIGINT, lambda *_: window.close())
        signal.signal(signal.SIGTERM, lambda *_: window.close())
        _wake = QTimer()
        _wake.start(200)
        _wake.timeout.connect(lambda: None)
    elif os.environ.get("SOP_FULLSCREEN", "0") == "1":
        window.showMaximized()
    else:
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
