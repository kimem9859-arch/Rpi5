import sys
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtCore import Qt, pyqtSignal
app = QApplication(sys.argv)
class Plain(QWidget): pass
class WithSig(QWidget):
    s = pyqtSignal()
def probe(cls, attr=None):
    root = QWidget(); root.resize(100,100); root.setStyleSheet("background:#000;")
    w = cls(root); w.setGeometry(10,10,80,80)
    if attr is not None: w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, attr)
    w.setStyleSheet("background: transparent; border: 9px solid #ff0000;")
    root.show(); app.processEvents()
    img = root.grab().toImage()
    c = img.pixelColor(12, 50)
    return (cls.__name__, attr, w.metaObject().className(), w.testAttribute(Qt.WidgetAttribute.WA_StyledBackground), c.name())
for args in ((QWidget,), (Plain,), (WithSig,), (Plain, True), (WithSig, False)):
    print(probe(*args))
