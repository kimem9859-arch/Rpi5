import os
import sys

try:
    import torch
    from ultralytics import YOLO
except Exception:
    pass

# Windows Qt 플러그인 경로 수동 지정 (라즈베리파이에서는 무시됨)
if sys.platform == "win32":
    for site_path in sys.path:
        plugin_path = os.path.join(site_path, "PyQt5", "Qt5", "plugins", "platforms")
        if os.path.exists(plugin_path):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path
            break

from PyQt5.QtWidgets import QApplication
from safety_console import SafetyConsole


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QMainWindow { background-color: #16213e; }
        QWidget     { background-color: #16213e; }
    """)
    window = SafetyConsole()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
