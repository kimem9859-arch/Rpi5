"""스침 판정 카드 — 시연 화면 오른쪽 아래(상태 막대 바로 위) · 세로 게이지 2개(왼쪽 머무름 · 오른쪽 손끝 속도)
(2026-10-22 사용자 시안 B2 · 값 = graze_gauge.GrazeTracker.view()).

🔴 판정은 하지 않는다 — 기준선(머무름 0.3초 · 속도 기준)은 판정기 설정값을 그대로 받아 그린다.
🔴 QGraphicsEffect 를 쓰지 않는다(overlay._glow 참고) — 도형 · 글자만 직접 그린다.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import config
import theme
from overlay import _qcolor, vplace

W, H = 360, 448                      # 시안 크기(영상 칸 1707×1280 기준 px)


def _name(btn):
    """「분홍 B3」 — 색 이름(안내와 같은 이름 · config 한 곳) + 버튼."""
    c = config.BUTTON_COLOR_NAMES.get(btn or "", "")
    return f"{c} {btn}".strip() if btn else ""


class GrazeCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._view = {"mode": "idle"}
        self._dwell, self._slow, self._scale = 0.3, 700.0, 1.0
        self._key = None

    # ------------------------------------------------------------------ 값
    def set_view(self, view, dwell_sec, slow_px_s_vga, px_scale):
        """view = GrazeTracker.view() · 속도는 판정기 단위(VGA px/s) — 화면 단위(× px_scale)로 바꿔 그린다."""
        self._view, self._dwell = view, float(dwell_sec)
        self._slow, self._scale = float(slow_px_s_vga) * px_scale, float(px_scale)
        sp = lambda v: None if v is None else round(v * px_scale)          # noqa: E731
        key = (view.get("mode"), view.get("btn"), view.get("exp"), view.get("kind"),
               round(view.get("elapsed") or 0.0, 2), sp(view.get("min")), sp(view.get("cur")), round(self._slow))
        if key != self._key:              # 바뀐 것이 있을 때만 다시 그린다
            self._key = key
            self.update()

    # ------------------------------------------------------------------ 그리기
    def _font(self, px, w=600):
        f = config.font("sub", w)
        f.setPixelSize(max(8, int(round(px * self.height() / H))))
        return f

    def paintEvent(self, _event):
        v, s = self._view, self.height() / H
        mode = v.get("mode", "idle")
        X = lambda x: x * s                 # noqa: E731
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if mode == "idle":
            p.setOpacity(0.55)
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(_qcolor(theme.C("panel_border")), 1))
        bg = _qcolor(theme.C("panel_bg"))
        bg.setAlpha(235)                    # 시안 B2 = 거의 불투명 — 종전 패널(68%)이면 뒤 버튼 이름표가 비쳤다(10/22 녹화)
        p.setBrush(bg)
        p.drawRoundedRect(card, X(14), X(14))
        x0, w0 = X(22), card.width() - X(44)
        text, label = _qcolor(theme.C("text")), _qcolor(theme.C("label"))
        warn, ok = _qcolor(theme.C("warn")), _qcolor(theme.C("done"))

        p.setFont(self._font(26, 700)); p.setPen(text)
        p.drawText(QRectF(x0, X(16), w0, X(34)), Qt.AlignmentFlag.AlignVCenter, "스침 판정")
        btn = v.get("btn")
        if btn:                             # 판정 중인 버튼(남은 단계 상자색 · 이름표와 같은 색)
            p.setFont(self._font(18, 700))
            tw = p.fontMetrics().horizontalAdvance(_name(btn)) + X(20)
            r = QRectF(card.right() - X(22) - tw, X(18), tw, X(30))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(_qcolor(theme.C("todo"))); p.drawRoundedRect(r, X(6), X(6))
            p.setPen(QColor("#141414")); p.drawText(r, Qt.AlignmentFlag.AlignCenter, _name(btn))
        p.setFont(self._font(16, 400)); p.setPen(label)
        if mode == "idle":
            lines = ("대기 — 손이 다른 버튼에 가면", "판정 과정이 여기 보입니다")
        else:
            lines = (f"지금 차례 = {_name(v.get('exp'))}", "다른 버튼은 빨리 지나가면 통과")
        for i, ln in enumerate(lines):
            p.drawText(QRectF(x0, X(54 + 22 * i), w0, X(22)), Qt.AlignmentFlag.AlignVCenter, ln)

        gt, gb, gw = X(142), X(352), X(38)
        kind = v.get("kind")
        el = v.get("elapsed")
        top = self._dwell * 1.2                                  # 0.3초 눈금이 위쪽 5/6 에 오게
        dwell_fill = None if el is None else min(1.0, el / top)
        fill_c = ok if kind == "pass" else warn
        self._vgauge(p, X(95), gt, gb, gw, "머무름", "—" if el is None else f"{el:.2f}초", fill_c,
                     self._dwell / top, f"{self._dwell:g}초\n= 경고", fill=dwell_fill, fill_color=fill_c)
        spd = v.get("cur") if mode == "judging" else v.get("min")
        mn = v.get("min")
        span = self._slow * 2 if self._slow > 0 else 1400.0
        mk = None if spd is None else min(1.0, spd * self._scale / span)
        val_c = ok if (mn is None or mn * self._scale > self._slow) else warn
        self._vgauge(p, X(245), gt, gb, gw, "손끝 속도",
                     "—" if mn is None else f"{mn * self._scale:,.0f} px/s", val_c,
                     0.5, f"{self._slow:,.0f}\n= 기준",
                     zones=[(0, 0.5, warn, 120), (0.5, 1.0, ok, 80)], marker=mk)
        p.setFont(self._font(13, 400)); p.setPen(label)
        p.drawText(QRectF(X(245) - X(92), gb - X(46), X(70), X(40)),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "느림 →\n바로 경고")

        if mode != "idle":                   # 맨 아래 판정 줄
            if mode == "judging":
                txt, bg, fg = "판정 중 — 아직 경고 아님", _qcolor(theme.C("panel_bg")), text
            elif kind == "pass":
                tail = "빠름" if mn is not None else "링만 스침"
                txt, bg, fg = f"스침 인정  {el:.2f}초 · {tail}", ok, QColor("#0e1013")
            elif kind == "slow":
                txt, bg, fg = (f"경고 · 느린 진입  {(mn or 0) * self._scale:,.0f}px/s(기준 {self._slow:,.0f})",
                               warn, QColor("#0e1013"))
            else:
                txt, bg, fg = f"경고 · 머무름  {self._dwell:g}초를 넘김", warn, QColor("#0e1013")
            p.setFont(self._font(18, 700))
            tw = min(card.width() - X(24), p.fontMetrics().horizontalAdvance(txt) + X(32))
            r = QRectF(card.center().x() - tw / 2, card.bottom() - X(52), tw, X(38))
            p.setPen(QPen(_qcolor(theme.C("panel_border")), 1) if mode == "judging" else Qt.PenStyle.NoPen)
            p.setBrush(bg); p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setPen(fg); p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)
        p.end()

    def _vgauge(self, p, cx, gt, gb, gw, title, value, value_color, tick, tick_txt,
                fill=None, fill_color=None, zones=None, marker=None):
        s = self.height() / H
        p.setFont(self._font(19, 600)); p.setPen(_qcolor(theme.C("todo")))
        p.drawText(QRectF(cx - 80 * s, gt - 36 * s, 160 * s, 26 * s), Qt.AlignmentFlag.AlignCenter, title)
        t = QRectF(cx - gw / 2, gt, gw, gb - gt)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 40)); p.drawRoundedRect(t, 9 * s, 9 * s)
        for a, b, c, alpha in zones or ():
            cc = QColor(c); cc.setAlpha(alpha)
            p.setBrush(cc); p.drawRect(QRectF(t.left(), t.bottom() - b * t.height(), t.width(), (b - a) * t.height()))
        if fill:
            p.setBrush(fill_color)
            p.drawRoundedRect(QRectF(t.left(), t.bottom() - fill * t.height(), t.width(), fill * t.height()), 9 * s, 9 * s)
        if marker is not None:
            my = t.bottom() - marker * t.height()
            p.setBrush(value_color); p.drawRoundedRect(QRectF(t.left() - 7 * s, my - 4 * s, t.width() + 14 * s, 8 * s), 3, 3)
        ty = t.bottom() - tick * t.height()
        p.setPen(QPen(_qcolor(theme.C("text")), 2)); p.drawLine(QPointF(t.left() - 8 * s, ty), QPointF(t.right() + 8 * s, ty))
        p.setFont(self._font(14, 400)); p.setPen(_qcolor(theme.C("label")))
        p.drawText(QRectF(t.right() + 10 * s, ty - 22 * s, 70 * s, 44 * s),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tick_txt)
        p.setFont(self._font(19, 700)); p.setPen(value_color)
        p.drawText(QRectF(cx - 90 * s, gb + 8 * s, 180 * s, 28 * s), Qt.AlignmentFlag.AlignCenter, value)

    # ------------------------------------------------------------------ 배치 · 테마
    def apply_theme(self):
        self.update()

    def relayout(self, vr):
        # 상태 막대(1294, 1204, 380×44)의 오른쪽 끝에 맞춰 바로 위(12px 띄움)
        vplace(self, vr, 1294 + 380 - W, 1204 - 12 - H, W, H)
