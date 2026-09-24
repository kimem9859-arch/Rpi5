import sys
sys.path.insert(0, "/home/pi/sop-project/Rpi5/Demo")
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import QRect
app = QApplication(sys.argv)
import theme, overlay
theme.PANEL_BACKGROUND = (sys.argv[-1] == "on")
root = QWidget(); root.resize(800, 600); root.setStyleSheet("background:#808080;")
glow = overlay.GlowFrame(root); glow.relayout(root.rect())
alert = overlay.AlertBanner(root)
alert.apply_theme()                 # _init_ui -> _apply_theme 와 같은 순서
glow.set_level("block")
alert.show_block()
alert.setGeometry(QRect(200, 200, 400, 150))
root.show(); app.processEvents()
img = root.grab().toImage()
print("PANEL_BACKGROUND", theme.PANEL_BACKGROUND)
print("glow border px (x=101,y=300):", img.pixelColor(101, 300).name(), " expected danger", theme.C("danger"))
print("alert bg px (205,290):", img.pixelColor(205, 290).name(), " (sheet bg would be near #0d0d0d over gray)")
print("alert border px (200,300):", img.pixelColor(200, 300).name())
