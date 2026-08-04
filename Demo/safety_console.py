import os
import time
import subprocess
from datetime import datetime

import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QTextBrowser, QPushButton, QSizePolicy,
    QDialog, QApplication, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

import config
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    RECORDING_ENABLED, RECORDING_SAVE_DIR, RECORDING_FPS, RECORDING_CODEC,
    LOG_SAVE_DIR,
    CAMERA_TCP_HOST, CAMERA_TCP_PORT,
    YOLO_CALIBRATION_PATH,
    BG_PRIMARY, BG_PANEL, BG_SURFACE, BG_LOG,
    BORDER_COLOR, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_LOG,
    ACCENT, BTN_ACTIVE, BTN_INACTIVE, BTN_CALIB,
    STATUS_OK, STATUS_WARNING, STATUS_DANGER,
)
from camera_thread import CameraThread, UsbCameraThread, close_detector
from fsm import SafetyFSM, State, Feedback
from roi_zones import INSIDE as ZONE_INSIDE
from recipe import load_recipe, RecipeError
from interlock import InterlockController
from gpio_input import GpioInputController

import theme
from sub_task import SubTask
from overlay import StatusPanel, GaugePanel, GlowFrame, AlertBanner, ConnBar, place
from overlay_menu import (MenuPanel, NotifyPanel, SettingsPanel,
                          NotifyButton, CheckPanel, RecordPanel)
import precheck


# =============================================================================
# [캘리브레이션 다이얼로그]
# =============================================================================
class CalibrationDialog(QDialog):
    CHESSBOARD   = (7, 5)
    SAMPLE_COUNT = 20
    DETECT_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH |
                    cv2.CALIB_CB_NORMALIZE_IMAGE  |
                    cv2.CALIB_CB_FAST_CHECK)

    _CHESSBOARD_PATH = os.path.join(os.path.dirname(__file__), 'chessboard.png')

    def __init__(self, camera_thread, parent=None):
        super().__init__(parent)
        self.setWindowTitle("캘리브레이션 — 체스보드를 카메라에 보여주세요")
        self.setModal(False)
        self.setFixedSize(520, 480)
        self.setStyleSheet(f"background-color: {BG_PRIMARY}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLOR};")

        self._camera_thread = camera_thread
        self._captured      = 0
        self._obj_points    = []
        self._img_points    = []
        self._last_cap_t    = 0.0
        self._frame_size    = None
        self._done          = False

        objp = np.zeros((self.CHESSBOARD[0] * self.CHESSBOARD[1], 3), np.float32)
        objp[:, :2] = np.mgrid[0:self.CHESSBOARD[0], 0:self.CHESSBOARD[1]].T.reshape(-1, 2)
        self._objp = objp

        # 체스보드 이미지
        self._board_label = QLabel()
        self._board_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._board_label.setStyleSheet(f"background-color: {BG_SURFACE}; border: 1px solid {BORDER_COLOR};")
        self._board_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._load_chessboard_image()

        self._status_label = QLabel(f"메인 화면을 보며 체스보드를 카메라에 비춰주세요  (0 / {self.SAMPLE_COUNT})")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(f"font-size: 13px; padding: 6px; color: {TEXT_PRIMARY}; background-color: {BG_PANEL};")

        self._cancel_btn = QPushButton("취소")
        self._cancel_btn.setStyleSheet(
            f"background-color: {STATUS_DANGER}; color: {TEXT_PRIMARY};"
            f"padding: 6px 18px; border-radius: 2px; font-size: 13px; font-weight: bold; border: none;"
        )
        self._cancel_btn.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._board_label)
        layout.addWidget(self._status_label)
        layout.addWidget(self._cancel_btn, alignment=Qt.AlignmentFlag.AlignRight)

        camera_thread._calibration_active = True
        camera_thread.raw_frame_signal.connect(self._on_frame)

    def _load_chessboard_image(self):
        if os.path.exists(self._CHESSBOARD_PATH):
            self._board_label.setPixmap(
                QPixmap(self._CHESSBOARD_PATH).scaled(
                    500, 400, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            self._board_label.setText("chessboard.png 파일을 Demo 폴더에 넣어주세요")
            self._board_label.setStyleSheet(f"color: {STATUS_DANGER}; font-size: 14px; background-color: {BG_SURFACE};")

    # -------------------------------------------------------------------------
    @pyqtSlot(object)
    def _on_frame(self, frame):
        if self._done:
            return

        self._frame_size = (frame.shape[1], frame.shape[0])
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        found, corners = cv2.findChessboardCorners(gray, self.CHESSBOARD, self.DETECT_FLAGS)

        if found:
            corners2 = cv2.cornerSubPix(
                gray, corners, (11, 11), (-1, -1),
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001),
            )
            now = time.time()
            if now - self._last_cap_t >= 1.0:
                self._obj_points.append(self._objp)
                self._img_points.append(corners2)
                self._captured += 1
                self._last_cap_t = now
                self._status_label.setText(
                    f"인식됨! 캡처: {self._captured} / {self.SAMPLE_COUNT}"
                )
                if self._captured >= self.SAMPLE_COUNT:
                    self._run_calibration()
        else:
            self._status_label.setText(
                f"체스보드를 찾는 중...  ({self._captured} / {self.SAMPLE_COUNT})"
            )

    def _run_calibration(self):
        self._done = True
        self._cleanup()
        self._status_label.setText("캘리브레이션 계산 중...")
        QApplication.processEvents()

        w, h = self._frame_size
        ret, cam_mat, dist, _, _ = cv2.calibrateCamera(
            self._obj_points, self._img_points, (w, h), None, None
        )
        np.savez(
            YOLO_CALIBRATION_PATH,
            camera_matrix=cam_mat,
            dist_coeffs=dist,
            image_size=np.array([w, h]),
        )
        self._status_label.setText(
            f"완료!  RMS 오차: {ret:.4f}  —  camera_calibration.npz 저장됨"
        )
        QTimer.singleShot(2000, self.accept)

    def _cleanup(self):
        try:
            self._camera_thread.raw_frame_signal.disconnect(self._on_frame)
        except Exception:
            pass
        self._camera_thread._calibration_active = False

    def reject(self):
        self._cleanup()
        super().reject()

    def closeEvent(self, event):
        self._cleanup()
        event.accept()


# =============================================================================
# [메인 콘솔]
# =============================================================================
class SafetyConsole(QMainWindow):

    # 물리 GPIO 버튼 입력 → GUI 스레드로 마샬링용 시그널(gpiozero 콜백은 별도 스레드).
    gpio_button_signal = pyqtSignal(str)
    # 백그라운드 스레드(인터락 워커·재연결, gpiozero)의 로그 → GUI 스레드 마샬링.
    # _append_log 는 Qt 위젯을 만지므로 비GUI 스레드에서 직접 호출 금지.
    bg_log_signal = pyqtSignal(str)
    # 인터락 폴트(BLOCK 차단 미확인) → GUI 스레드 알람.
    interlock_fault_signal = pyqtSignal(str)
    # 연결 포기(5회 실패) → 알림. 인터락은 워커 스레드에서 오므로 마샬링이 필요하다.
    connect_gave_up_signal = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vision AI 안전 콘솔")
        # 창 크기: 기본은 설계값(1280×720)이나 **고정하지 않는다**.
        # 시나리오 촬영 때 모니터를 꽉 채워야 화면 녹화에 GUI가 크게 담긴다.
        # 영상은 camera_label 크기에 맞춰 비율 유지로 스케일되므로(_update_camera_frame)
        # 창을 키워도 왜곡되지 않는다. ※ ESP32 녹화본 해상도는 창 크기와 무관하다.
        self.setMinimumSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._active_camera = "esp32"
        self._last_yolo_classes = set()
        self._last_roi = (None, 0)   # (ROI 라벨, 구역 단계) — 로그 중복 억제용

        # 서브 작업(대기·공구) — design §5. FSM 을 고치지 않는 대신 여기서 굴린다.
        self._sub = None             # 진행 중인 SubTask
        self._sub_button = None      # 그 서브 작업을 시작시킨 버튼
        self._tool_override = None   # 설정 메뉴에서 바꾼 지정 공구(세션 한정)
        self._unread = 0             # 안 읽은 알림 수 — 배지에 표시
        self._recording_mode = "full"
        self._recording_size = (WINDOW_WIDTH, WINDOW_HEIGHT)
        self._recording_started = 0.0
        self._last_frame_size = None     # 카메라 영역 녹화 크기 결정용
        self._last_qimage = None         # 점검(손 검출 추론)용 최근 프레임(지연 변환)
        self._last_frame_time = 0.0
        self._seen_buttons = set()       # 2차 점검 — 지금 화면에 보이는 버튼
        self._sub_timer = QTimer()
        self._sub_timer.setInterval(200)
        self._sub_timer.timeout.connect(self._tick_sub)

        # 공정 레시피(정답 순서 단일 출처, §6) 로드. 실패해도 기본 시퀀스로 동작.
        try:
            self._recipe = load_recipe()
        except RecipeError as e:
            self._recipe = None
            print(f"[레시피] 로드 실패 — 기본 시퀀스로 진행: {e}")

        # 판정부(FSM) — 통합문서 §9. 콜백으로 상태표시·인터록·피드백을 받는다.
        self.fsm = SafetyFSM(
            sequence=(self._recipe["steps"] if self._recipe else None),
            dwell_threshold=(self._recipe["dwell_threshold_sec"] if self._recipe else None),
            emo_button=(self._recipe["emo_button"] if self._recipe else None),
            on_state_change=self._on_fsm_state,
            on_interlock=self._on_interlock,
            on_feedback=self._on_feedback,
        )

        self._video_writer   = None
        self._recording      = False
        self._recording_path = ""

        self._recording_timer = QTimer()
        self._recording_timer.setInterval(int(1000 / RECORDING_FPS))
        self._recording_timer.timeout.connect(self._capture_window_frame)

        os.makedirs(LOG_SAVE_DIR, exist_ok=True)
        log_filename = datetime.now().strftime("%Y%m%d_%H%M%S") + "_log.txt"
        self._log_file_path = os.path.join(LOG_SAVE_DIR, log_filename)

        self._init_ui()

        # 트랙 A 물리 인터락 — FSM 콜백을 Arduino 릴레이 명령으로(시리얼).
        # 미연결 시 예외 없이 fallback(로그만)이라 GUI 동작에는 영향 없음.
        # 로그·폴트는 워커/재연결 스레드에서 오므로 시그널로 GUI 스레드에 마샬링.
        # _append_log 가 쓰는 log_browser·_log_file_path 가 준비된 _init_ui 이후 생성.
        self.bg_log_signal.connect(self._append_log)
        self.interlock_fault_signal.connect(self._on_interlock_fault)
        self.connect_gave_up_signal.connect(self._on_connect_gave_up)
        self.interlock = InterlockController(
            log=self.bg_log_signal.emit,
            on_fault=self.interlock_fault_signal.emit,
            on_give_up=lambda n: self.connect_gave_up_signal.emit("인터락", n))

        # 트랙 A 물리 입력 — 버튼 B1~B4·EMO(GPIO) → FSM. gpiozero 콜백은 별도 스레드라
        # 시그널로 GUI 스레드의 _press_button 에 마샬링(직접 GUI 접근 금지). 미연결·비-Pi
        # 환경에선 fallback(로그만) → 키보드 시뮬(1~4·E)로 동일 동작.
        self.gpio_button_signal.connect(self._press_button)
        self.gpio_input = GpioInputController(
            on_button=self.gpio_button_signal.emit, log=self.bg_log_signal.emit)

        self.camera_thread = CameraThread()
        self.camera_thread.change_pixmap_signal.connect(self._update_camera_frame)
        self.camera_thread.log_signal.connect(self._append_log)
        self.camera_thread.yolo_detections_signal.connect(self._on_yolo_detections)
        self.camera_thread.roi_signal.connect(self._on_roi)
        self.camera_thread.calibration_needed_signal.connect(self._on_calibration_needed)
        self.camera_thread.connect_failed_signal.connect(
            lambda n: self._on_connect_gave_up("카메라", n))
        self.camera_thread.start()

        # 🔴 두 카메라를 동시에 돌리지 않는다 (2026-08-04).
        #    종전에는 ESP32·USB 스레드가 **둘 다 추론**했는데 화면엔 하나만 나왔다.
        #    실측에서 USB 쪽이 약 14%p 를 쓰고 있었다. 쓰는 쪽만 돌린다.
        self.usb_camera_thread = UsbCameraThread()
        self.usb_camera_thread.change_pixmap_signal.connect(self._update_usb_frame)
        self.usb_camera_thread.log_signal.connect(self._append_log)
        self.usb_camera_thread.yolo_detections_signal.connect(self._on_yolo_detections)
        self.usb_camera_thread.roi_signal.connect(self._on_roi)
        # start() 는 _switch_camera 가 필요할 때만 부른다 — 아래 초기 전환에서 결정된다.

        self._switch_camera("esp32", quiet=True)   # 기동 시 ESP32 만 — USB 는 CCTV 전환 때 연다
        self._append_log("[시스템] Vision AI 안전 콘솔 시작")
        if self._recipe:
            self._append_log(f"[레시피] '{self._recipe['process_name']}' 로드 — {self.fsm.step_count}단계")
        else:
            self._append_log("[레시피] 파일 없음/오류 — 기본 시퀀스(B1~B4)로 진행")
        # 손 검출은 모델·소스가 없으면 **조용히** 비활성된다(hand_tracker.py). 시작 로그에
        # 상태를 못 박아 둬야 "왜 순서 위반을 못 잡지?"를 나중에 헤매지 않는다.
        # ※ HandTracker 자신도 로그를 내지만 CameraThread.__init__ 시점이라 log_signal 이
        #    아직 연결되기 전이다 — GUI 로그에는 안 남는다. 그래서 여기서 다시 적는다.
        _hand = self.camera_thread._hand
        self._append_log(f"[시스템] 손 검출(HOI): {'사용 가능' if _hand.available else '비활성 — ' + _hand.reason}")
        # 🔴 폰트가 조용히 폴백되면 알 방법이 없다 — 2026-08-03 이전 3개월간 Consolas 요청이
        #    중국어 폰트로 대체되고 있었다. 요청/실제를 여기서 못 박는다.
        self._append_log(f"[시스템] UI 폰트: {config.font_report()}")
        self._append_log(f"[시스템] ESP32-S3 카메라: {CAMERA_TCP_HOST}:{CAMERA_TCP_PORT} (TCP)")
        self._append_log(f"[시스템] 로그 저장: {self._log_file_path}")

        if RECORDING_ENABLED:
            QTimer.singleShot(500, self._start_recording)

    # =========================================================================
    # [UI 초기화]
    # =========================================================================
    def _init_ui(self):
        """글라스 UI — 영상 가운데 4:3, 좌우 검정 레터박스, 모든 UI 는 오버레이.

        정본 = 상위 specs/2026-08-03-uiux-글라스-design.md §1·§4.
        기존 좌7:우3 2단 배치를 대체한다.
        """
        central = QWidget()
        central.setStyleSheet(f"background-color: #000000;")
        self.setCentralWidget(central)
        self._root = central

        # ── 영상 (가운데 4:3, 나머지는 검정) ────────────────────────────────
        self.camera_label = QLabel("카메라 연결 대기 중...", central)
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setStyleSheet("background-color: #000000; color: #8d949a;")

        # 패널이 열렸을 때 뒤를 어둡게 하는 반투명 판. 효과 대신 쓴다(_dim_others).
        self.scrim = QWidget(central)
        self.scrim.hide()

        # ── 오버레이 ───────────────────────────────────────────────────────
        steps = self._recipe["steps"] if self._recipe else [
            {"order": i + 1, "button": f"B{i + 1}", "name": f"{i + 1}단계"}
            for i in range(self.fsm.step_count)
        ]
        self.status_panel = StatusPanel(steps, central)
        self.gauge_panel  = GaugePanel(central)
        self.glow         = GlowFrame(central)
        self.alert        = AlertBanner(central)
        self.alert.release_clicked.connect(self._on_alert_release)

        # ── 버튼 (메뉴·알림·CTA) ───────────────────────────────────────────
        self.btn_menu = QPushButton("☰", central)
        self.btn_menu.setFont(config.font("cta", 700))
        self.btn_menu.setCursor(Qt.CursorShape.PointingHandCursor)
        # 🔴 clicked 는 checked(False) 를 인자로 보낸다 — 그대로 연결하면
        #    _toggle_menu(show=False) 가 되어 **열자마자 닫힌다.** 인자를 버린다.
        self.btn_menu.clicked.connect(lambda: self._toggle_menu())

        self.btn_notify = NotifyButton(central)
        self.btn_notify.setFont(config.font("cta", 700))
        self.btn_notify.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_notify.clicked.connect(lambda: self._toggle_notify())

        # 작업 시작 / 다음 단계 진행 — 화면 정중앙(design §4.1·§4.3)
        self.btn_cta = QPushButton("▶  작업 시작", central)
        self.btn_cta.setFont(config.font("cta", 800))
        self.btn_cta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cta.clicked.connect(lambda: self._on_cta())

        # 🔴 버튼이 포커스를 가져가면 keyPressEvent(ESC·1~4·E)가 안 온다.
        for b in (self.btn_menu, self.btn_notify, self.btn_cta):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # ── 시트 패널 (열었을 때만) ────────────────────────────────────────
        self.menu_panel = MenuPanel(central)
        self.menu_panel.closed.connect(lambda: self._toggle_menu(False))
        self.menu_panel.log_clicked.connect(self._show_log)
        self.menu_panel.calibrate_clicked.connect(lambda: self._open_calibration_dialog())
        self.menu_panel.cctv_clicked.connect(self._toggle_camera_source)
        self.menu_panel.check_clicked.connect(self._open_check)
        self.menu_panel.record_clicked.connect(self._open_record)
        self.menu_panel.settings_clicked.connect(self._open_settings)
        self.menu_panel.shutdown_clicked.connect(lambda: self._on_shutdown_clicked())

        self.notify_panel = NotifyPanel(central)
        self.notify_panel.closed.connect(lambda: self._toggle_notify(False))

        self.check_panel = CheckPanel(central)
        self.check_panel.retry_requested.connect(self._on_retry)
        self.check_panel.recheck_requested.connect(self._run_manual_check)

        self.record_panel = RecordPanel(central)
        self.record_panel.start_requested.connect(self._start_recording)
        self.record_panel.stop_requested.connect(self._stop_recording)
        self.record_panel.set_save_dir(RECORDING_SAVE_DIR)
        self.record_panel.open_folder_requested.connect(self._open_recordings_folder)

        # 🔴 항목 패널은 ✕ 로 닫는다 (2026-08-04) — 메뉴·알림 창 자체는 같은 버튼
        #    재클릭으로 닫는 방식을 그대로 둔다. 캘리브레이션은 별도 대화상자라 제외.
        self.check_panel.closed.connect(lambda: self._toggle_sheet(self.check_panel, False))
        self.record_panel.closed.connect(lambda: self._toggle_sheet(self.record_panel, False))

        self.settings_panel = SettingsPanel(central)
        self.settings_panel.closed.connect(lambda: self._toggle_settings(False))
        self.settings_panel.tool_changed.connect(self._on_tool_changed)
        self.settings_panel.theme_changed.connect(self._on_theme_changed)
        self.settings_panel.panel_bg_changed.connect(self._on_panel_bg_changed)
        self.settings_panel.closed.connect(lambda: self._toggle_settings(False))
        # 공구 선택지는 **레시피가 준다** — 목록을 코드에 박지 않는다(design §4.4).
        self._wire_tool_settings()

        # 우하단 연결 상태 표시바 — 상시 노출(design §9)
        self.conn_bar = ConnBar(central)
        self.conn_bar.show()

        # 로그는 메뉴 안으로 — 평소엔 숨는다(design §4.7)
        self.log_browser = QTextBrowser(central)
        self.log_browser.setFont(config.font("small"))
        self.log_browser.hide()
        # 로그는 _Sheet 가 아니라 QTextBrowser 다 — ✕ 를 따로 얹는다.
        # 🔴 부모를 log_browser 로 두면 **뷰포트가 그 위를 덮어 보이지 않는다**
        #    (QAbstractScrollArea 는 자식을 뷰포트 아래에 둔다. 2026-08-04 확인).
        #    그래서 central 의 자식으로 두고 _relayout 이 로그창 우상단에 앉힌다.
        self._log_close = QPushButton("✕", central)
        self._log_close.setFont(config.font("banner", 700))   # ✕ 글리프는 작게 그려진다
        self._log_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._log_close.setFlat(True)
        self._log_close.setFixedSize(32, 32)
        self._log_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._log_close.clicked.connect(lambda: self._set_log_visible(False))
        self._log_close.hide()

        # 연결 상태바는 1초마다 갱신한다 — 색만 바꾸는 갱신이라 부하가 없다.
        self._conn_timer = QTimer(self)
        self._conn_timer.timeout.connect(self._update_conn_bar)
        self._conn_timer.start(1000)

        self._apply_theme()
        self._relayout()

    # =========================================================================
    # [글라스 UI — 배치·테마]
    # =========================================================================
    def _relayout(self):
        """창 크기가 바뀔 때마다 % 기준으로 다시 배치한다."""
        if not hasattr(self, "_root"):
            return
        # ⚠️ QMainWindow 가 centralWidget 을 언제 resize 하는지는 이벤트 순서에 달려
        #    있어, 여기서 직접 맞춘다. 안 그러면 창을 키워도 오버레이가 옛 크기로 앉는다.
        self._root.setGeometry(self.contentsRect())
        r = self._root.rect()
        pw, ph = r.width(), r.height()

        # 영상: 가운데 4:3(높이를 꽉 채움). 좌우가 검정 레터박스가 된다.
        vh = ph
        vw = int(vh * 4 / 3)
        if vw > pw:                       # 창이 4:3보다 좁으면 폭 기준
            vw, vh = pw, int(pw * 3 / 4)
        self.camera_label.setGeometry((pw - vw) // 2, (ph - vh) // 2, vw, vh)

        self.status_panel.relayout(r)
        self.gauge_panel.relayout(r)
        self.glow.relayout(r)
        self.alert.relayout(r)
        self.menu_panel.relayout(r)
        self.notify_panel.relayout(r)
        self.settings_panel.relayout(r)
        self.check_panel.relayout(r)
        self.record_panel.relayout(r)
        # 🔴 상태바만 **영상 사각형** 기준이다 — 창 기준이면 오른쪽 검정
        #    레터박스에 앉는다(2026-08-04).
        self.conn_bar.relayout(self.camera_label.geometry())

        place(self.btn_menu, r, right=0.14, top=0.05)
        place(self.btn_notify, r, left=0.14, bottom=0.05)
        place(self.btn_cta, r)            # 정중앙
        self.log_browser.setGeometry(int(pw * 0.14), int(ph * 0.10),
                                     int(pw * 0.50), int(ph * 0.80))
        r_log = self.log_browser.geometry()
        # 스크롤바(8px)와 겹치지 않게 안쪽으로 — 44 면 겹쳤다(2026-08-04).
        self._log_close.move(r_log.right() - 58, r_log.top() + 8)
        self._log_close.raise_()
        self.scrim.setGeometry(r)

        for w in (self.glow, self.alert, self.menu_panel, self.notify_panel,
                  self.settings_panel, self.check_panel, self.record_panel,
                  self.log_browser, self.btn_menu, self.btn_notify):
            w.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _apply_theme(self):
        """테마가 바뀌면 모든 오버레이에 다시 적용한다."""
        for w in (self.status_panel, self.gauge_panel, self.alert,
                  self.menu_panel, self.notify_panel, self.settings_panel,
                  self.check_panel, self.record_panel, self.conn_bar):
            w.apply_theme()
        btn_qss = (f"QPushButton {{ {theme.panel_qss('panel', padding='8px 14px')} }}"
                   f"QPushButton:hover {{ color: {theme.C('info')}; }}")
        self.btn_menu.setStyleSheet(btn_qss)
        self.btn_notify.setStyleSheet(btn_qss)
        self.btn_cta.setStyleSheet(
            f"QPushButton {{ background-color: {theme.C('cta_bg')};"
            f" color: {theme.C('cta_text')}; border: 1px solid {theme.C('cta_border')};"
            f" border-radius: 12px; padding: 18px 42px; }}")
        self.log_browser.setStyleSheet(
            theme.panel_qss("sheet", padding="10px 12px")
            + f"color: {theme.C('text')};")
        self._log_close.setStyleSheet(
            f"QPushButton {{ color: {theme.C('text')}; background: transparent;"
            f" border: none; }}"
            f"QPushButton:hover {{ color: {theme.C('info')}; }}")
        self.scrim.setStyleSheet(
            "background-color: rgba(0, 0, 0, 0.55);" if theme.current() == "dark"
            else "background-color: rgba(0, 0, 0, 0.35);")


    # =========================================================================
    # [슬롯]
    # =========================================================================
    @pyqtSlot(QImage)
    def _update_camera_frame(self, qt_image):
        if self._active_camera != "esp32":
            return
        self._note_frame(qt_image)
        scaled = qt_image.scaled(
            self.camera_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.camera_label.setPixmap(QPixmap.fromImage(scaled))

    @pyqtSlot(QImage)
    def _update_usb_frame(self, qt_image):
        if self._active_camera != "usb":
            return
        self._note_frame(qt_image)
        scaled = qt_image.scaled(
            self.camera_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.camera_label.setPixmap(QPixmap.fromImage(scaled))

    def _note_frame(self, qt_image):
        """프레임이 올 때마다 점검·녹화가 쓰는 정보를 갱신한다.

        - `_last_frame_time` : 2차 점검의 「영상 수신」이 신선도를 본다
        - `_last_frame_size` : 카메라 영역 녹화의 해상도
        - 카메라 영역 녹화면 여기서 바로 기록한다(창 캡처 없음)
        """
        self._last_frame_time = time.time()
        self._last_frame_size = (qt_image.width(), qt_image.height())
        # ⚠️ numpy 변환은 **점검이 요청할 때만** 한다(_frame_for_check).
        #    매 프레임 변환하면 GUI 스레드에 쓸데없는 부담이 생긴다.
        self._last_qimage = qt_image
        if self._recording and self._recording_mode == "camera":
            try:
                img = qt_image.convertToFormat(QImage.Format.Format_RGB888)
                w, h = img.width(), img.height()
                ptr = img.bits(); ptr.setsize(h * w * 3)
                arr = np.array(ptr).reshape(h, w, 3)
                self._record_camera_frame(cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
            except Exception as e:
                print(f"[녹화 프레임 오류] {e}")

    def _switch_camera(self, source, quiet=False):
        """카메라 전환 — 🔴 쓰는 쪽만 스레드를 돌린다(둘 다 돌리면 CPU 낭비).

        ⚠️ 멈춘 스레드를 다시 start() 할 수는 없다(QThread 규약). 그래서 쓰지 않는
           쪽은 **set_active(False) 로 처리만 끄고** 스레드는 유지한다. 처리를 끄면
           추론이 돌지 않아 부담이 사라진다 — 이것이 실측 14%p 의 정체였다.
        """
        self._active_camera = source
        self._last_yolo_classes = set()
        self.camera_thread.set_active(source == "esp32")
        self.usb_camera_thread.set_active(source == "usb")
        if source == "usb" and not self.usb_camera_thread.isRunning():
            self.usb_camera_thread.start()      # 필요해진 순간에만 연다
        label = "초소형카메라 (ESP32-S3)" if source == "esp32" else "CCTV (USB 웹캠)"
        self._append_log(f"[카메라] {label}로 전환")
        if not quiet:
            self._notify("work", "카메라 전환", label)
        if source == "esp32":
            self.camera_label.setText("ESP32-S3 연결 대기 중...")

    def _toggle_camera_source(self):
        """메뉴의 「CCTV 전환」 — 두 카메라를 번갈아 쓴다."""
        self._switch_camera("usb" if self._active_camera == "esp32" else "esp32")
        self._toggle_menu(False)

    # =========================================================================
    # [글라스 UI — 패널 열고 닫기]
    # =========================================================================
    # ⚠️ 열림 판정은 isHidden() 으로 한다 — 창이 아직 안 보이는 동안
    #    자식 위젯의 isVisible() 은 항상 False 라 토글이 엉킨다.
    def _toggle_menu(self, show=None):
        want = self.menu_panel.isHidden() if show is None else show
        if want:
            self._close_sheets(except_=self.menu_panel)
        self.menu_panel.setVisible(want)
        if want:
            self.menu_panel.raise_()
        self._dim_others(self._any_sheet_open())
        self._sync_cta_visibility()

    def _toggle_notify(self, show=None):
        want = self.notify_panel.isHidden() if show is None else show
        if want:
            self._close_sheets(except_=self.notify_panel)
        self.notify_panel.setVisible(want)
        if want:
            self.notify_panel.raise_()
            self._unread = 0                 # 열면 읽음 — 배지가 사라진다
            self.btn_notify.set_count(0)
        self._dim_others(self._any_sheet_open())
        self._sync_cta_visibility()

    def _toggle_settings(self, show=None):
        want = self.settings_panel.isHidden() if show is None else show
        if want:
            self._close_sheets(except_=self.settings_panel)
            # 🔴 공구는 IDLE 일 때만 바꿀 수 있다 — 진행 중에 바뀌면 판정이 흔들린다.
            self.settings_panel.set_tool_editable(self.fsm.state == State.IDLE)
        self.settings_panel.setVisible(want)
        if want:
            # 🔴 Task 3 과 같은 이유로 다시 배치한다 — 설정 패널은 높이를 지정하지
            #    않아 sizeHint 로 앉는데, 「작업 중에는 변경할 수 없습니다」 문구가
            #    생기면 필요 높이가 커진다. 다시 재지 않으면 **공구 라디오가 눌려
            #    겹친다**(2026-08-04 확인). 메뉴·알림은 높이를 비율로 지정해 무관.
            self.settings_panel.layout().activate()
            self.settings_panel.relayout(self._root.rect())
            self.settings_panel.raise_()
        self._dim_others(self._any_sheet_open())
        self._sync_cta_visibility()

    def _sheets(self):
        return (self.menu_panel, self.notify_panel, self.settings_panel,
                self.check_panel, self.record_panel)

    def _close_sheets(self, except_=None):
        """한 번에 하나만 열리게 한다 — 겹치면 뒤엣것을 못 읽는다."""
        for p in self._sheets():
            if p is not except_:
                p.hide()
        if except_ is not self.log_browser:
            self._set_log_visible(False)

    def _any_sheet_open(self):
        return any(not p.isHidden() for p in self._sheets())

    def _sync_cta_visibility(self):
        """시트가 열려 있는 동안 정중앙 CTA 를 감춘다 (2026-08-04).

        시트 배경이 rgba(…, 0.90) 이라 **뒤에 있는 파란 CTA 가 10% 배어 나온다.**
        클릭은 시트가 정상적으로 받으므로 기능 문제는 아니고 시각 노이즈다.

        🔴 시트를 닫을 때 무조건 show() 하면 안 된다 — CTA 가 숨어 있어야 하는
           상태가 따로 있다(버튼 눌림을 기다리는 중, 게이지가 덜 찼을 때).
           열기 직전 상태를 기억해 두는 방식도 안 된다. 시트를 열어 둔 사이에
           게이지가 다 차면 기억값이 어긋나 **버튼이 영영 안 나온다.**
           → 기억하지 말고 **상태에서 그때그때 계산한다.**
        """
        if self._any_sheet_open():
            self.btn_cta.hide()
            return
        if self._sub is not None and self._sub.is_active:
            show = self._sub.can_advance
        else:
            show = self.fsm.state == State.IDLE
        self.btn_cta.setVisible(show)
        if show:
            self.btn_cta.raise_()

    def _open_check(self):
        """메뉴 → 점검(연결). 🔴 재연결 5회 포기 후 다시 붙일 수 있는 유일한 수단."""
        self._toggle_menu(False)
        self._run_manual_check()
        self._toggle_sheet(self.check_panel, True)

    def _open_record(self):
        self._toggle_menu(False)
        self.record_panel.set_state(
            self._recording, self._recording_path,
            time.time() - self._recording_started if self._recording else 0)
        self._toggle_sheet(self.record_panel, True)

    def _open_recordings_folder(self):
        """저장 폴더를 파일관리자로 연다 (design §7).

        🔴 실패해도 GUI 가 멈추면 안 된다 — 파일관리자가 없거나 실행이 실패하면
           경로를 로그에 남기고 조용히 넘어간다. 시연 중에 예외로 죽는 쪽이 훨씬 나쁘다.
        """
        try:
            os.makedirs(RECORDING_SAVE_DIR, exist_ok=True)
            subprocess.Popen(["xdg-open", RECORDING_SAVE_DIR])
            self._append_log(f"[녹화] 저장 폴더 열기: {RECORDING_SAVE_DIR}")
        except Exception as e:
            self._append_log(
                f"[녹화] 폴더 열기 실패({type(e).__name__}) — 경로: {RECORDING_SAVE_DIR}")

    def _run_manual_check(self):
        """수동 점검 — 1차 항목을 지금 다시 본다."""
        self.check_panel.update_results(precheck.run_stage1(self._check_ctx()))

    def _update_conn_bar(self):
        """연결 상태바 — 🔴 점검(1차)과 **같은 출처**로 계산한다.

        따로 판단하면 표시바와 점검 화면이 서로 다른 말을 하게 된다.
        """
        ok = {r.key: r.ok for r in precheck.run_stage1(self._check_ctx(with_frame=False))}
        self.conn_bar.update_state({k: ok.get(k) for k in ("camera", "interlock", "gpio")})

    def _check_ctx(self, with_frame=True):
        """점검이 보는 대상 묶음. 1·2차·수동이 같은 것을 본다.

        with_frame=False — 연결 상태바처럼 매 초 부르는 곳은 프레임 변환을 건너뛴다
        (numpy 변환이 비싸다). 1차 점검은 프레임을 보지 않으므로 결과가 같다.
        """
        from camera_thread import DETECTOR_AVAILABLE
        cam = (self.camera_thread if self._active_camera == "esp32"
               else self.usb_camera_thread)
        return dict(
            camera_thread=cam,
            detector_available=DETECTOR_AVAILABLE,
            hand_tracker=getattr(cam, "_hand", None),
            interlock=self.interlock,
            gpio_input=self.gpio_input,
            last_frame_time=self._last_frame_time,
            last_frame=self._frame_for_check() if with_frame else None,
            seen_buttons=self._seen_buttons,
        )

    def _frame_for_check(self):
        """점검용 프레임 — 요청 시에만 numpy 로 바꾼다."""
        img = self._last_qimage
        if img is None:
            return None
        try:
            rgb = img.convertToFormat(QImage.Format.Format_RGB888)
            w, h = rgb.width(), rgb.height()
            ptr = rgb.bits(); ptr.setsize(h * w * 3)
            return cv2.cvtColor(np.array(ptr).reshape(h, w, 3), cv2.COLOR_RGB2BGR)
        except Exception:
            return None

    def _on_retry(self, key):
        """점검 화면의 「재연결」 버튼."""
        if key == "camera":
            for cam in (self.camera_thread, self.usb_camera_thread):
                if hasattr(cam, "retry_connect"):
                    cam.retry_connect()
            self._append_log("[점검] 카메라 재연결 요청")
        elif key in ("interlock", "interlock_ack"):
            self.interlock.retry_connect()
            self._append_log("[점검] 인터락 재연결 요청")
        else:
            self._append_log(f"[점검] {key} 재확인")
        QTimer.singleShot(1500, self._run_manual_check)

    def _toggle_sheet(self, panel, show=None):
        want = panel.isHidden() if show is None else show
        if want:
            self._close_sheets(except_=panel)
        panel.setVisible(want)
        if want:
            # 🔴 내용을 채운 뒤 **다시 배치**한다 — 패널은 내용이 비었을 때 잡힌
            #    크기로 앉아 있어, 항목을 채워도 다시 재지 않으면 납작하게 눌린다
            #    (2026-08-04: 점검 패널 첫 열기 89px, 정상 496px).
            #    여기 한 곳에 두면 앞으로 생길 패널도 자동으로 덕을 본다.
            panel.layout().activate()
            panel.relayout(self._root.rect())
            panel.raise_()
        self._dim_others(self._any_sheet_open())
        self._sync_cta_visibility()

    def _open_settings(self):
        self._toggle_menu(False)
        self._toggle_settings(True)

    def _set_log_visible(self, on):
        """로그 창과 그 ✕ 는 항상 함께 뜨고 함께 사라진다 — ✕ 가 별도 위젯이라
        (뷰포트에 가리지 않으려고 central 의 자식이다) 따로 두면 어긋난다."""
        self.log_browser.setVisible(on)
        self._log_close.setVisible(on)
        if on:
            self.log_browser.raise_()
            self._log_close.raise_()

    def _show_log(self):
        self._toggle_menu(False)
        self._set_log_visible(self.log_browser.isHidden())

    def _dim_others(self, dimmed):
        """열린 패널·경고가 주인공이 되도록 뒤를 어둡게 한다 (design §4.7·§4.5).

        🔴 **그래픽 효과를 쓰지 않는다.** QGraphicsOpacityEffect·DropShadowEffect 를
           오버레이에 걸었더니 Qt 가 "QPainter::begin: A paint device can only be
           painted by one painter at a time" 를 끝없이 뱉으며 **화면이 안 그려지고
           클릭도 안 먹었다**(2026-08-03 실기동에서 확인, CPU 60%).

        → 대신 **반투명 판(scrim) 한 장**을 영상과 시트 사이에 끼운다.
          위젯 하나뿐이라 효과가 겹칠 일이 없고, 영상과 뒤쪽 오버레이가 함께 어두워져
          목업과 같은 그림이 된다.
        """
        self.scrim.setVisible(dimmed)
        if dimmed:
            self.scrim.raise_()
            for p in self._sheets():
                if not p.isHidden():
                    p.raise_()
            # 🔴 버튼은 스크림 **위**에 있어야 한다 — 가려지면 "같은 버튼을 다시 눌러
            #    닫기"가 불가능해진다(2026-08-04 실기동에서 실제로 막혔다).
            self.btn_menu.raise_()
            self.btn_notify.raise_()
            if self.alert.mode:
                self.glow.raise_()
                self.alert.raise_()
            if not self.log_browser.isHidden():
                self.log_browser.raise_()

    # =========================================================================
    # [글라스 UI — 설정 반영]
    # =========================================================================
    def _wire_tool_settings(self):
        """레시피에서 공구 선택지를 찾아 설정 패널에 넘긴다.

        `wait_tool` 서브 작업이 없으면 공구 항목 자체가 비어 있게 둔다 —
        시나리오가 바뀌어도 코드를 안 고치게 하려는 것이다.
        """
        for s in (self._recipe or {}).get("steps", []):
            sub = s.get("sub") or {}
            if sub.get("type") == "wait_tool":
                self.settings_panel.set_tools(
                    sub.get("tools", []), sub.get("tool"), sub.get("tool_names"))
                return

    def _on_tool_changed(self, tool_key):
        self._tool_override = tool_key
        name = self._tool_display_name(tool_key)
        self._append_log(f"[설정] 지정 공구 → {name}")
        self._notify("work", "설정 변경", f"지정 공구 → {name}")

    def _on_theme_changed(self, name):
        theme.set_theme(name)
        self._apply_theme()
        self._relayout()
        self._append_log(f"[설정] 화면 테마 → {'다크' if name == 'dark' else '화이트'}")

    def _on_panel_bg_changed(self, on):
        """공정 단계·게이지 패널의 배경 on/off — 실기동 영상에서 확인 후 기본값 확정."""
        theme.PANEL_BACKGROUND = bool(on)
        self._apply_theme()
        self._relayout()
        self._append_log(f"[설정] 패널 배경 → {'있음' if on else '없음'}")

    def _tool_display_name(self, key):
        for s in (self._recipe or {}).get("steps", []):
            sub = s.get("sub") or {}
            if key in (sub.get("tools") or []):
                return sub.get("tool_names", {}).get(key, key)
        return key

    @pyqtSlot(str, int)
    def _on_connect_gave_up(self, what, tries):
        """연결을 포기했을 때 — 로그를 계속 쌓는 대신 알림 1건으로 알린다."""
        self._notify("warn", f"{what} 연결 실패",
                     f"{tries}회 시도 후 중단 — 메뉴 → 점검(연결)에서 다시 시도")

    def _notify(self, kind, title, sub=""):
        """알림 추가 + 배지 갱신. 배지는 **읽지 않은 수**를 보인다."""
        self.notify_panel.push(kind, title, sub)
        self._unread += 1
        self.btn_notify.set_count(self._unread)

    @pyqtSlot(str)
    def _append_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        self.log_browser.append(line)
        self.log_browser.verticalScrollBar().setValue(
            self.log_browser.verticalScrollBar().maximum()
        )
        try:
            with open(self._log_file_path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

    @pyqtSlot(list)
    def _on_yolo_detections(self, detections):
        current = set(d[0] for d in detections)
        self._seen_buttons = current      # 2차 점검 「버튼 검출」이 본다
        if current != self._last_yolo_classes:
            if current:
                self._append_log(f"[YOLO] 탐지: {', '.join(sorted(current))}")
            self._last_yolo_classes = current

    # =========================================================================
    # [판정부 FSM — 인식 입력 / 상태 출력]  통합문서 §8·§9
    # =========================================================================
    @pyqtSlot(str, int)   # 🔴 시그널(str, int)과 반드시 일치해야 한다 — 어긋나면 기동 즉시 TypeError
    def _on_roi(self, roi, level):
        """HOI 결과(손끝이 든 버튼 ROI + 구역 단계)를 FSM 비전 틱으로 전달.

        level: 2=박스 안(위험) / 1=링(접근) / 0=밖. 상세 = roi_zones.py
        """
        self.fsm.update_vision(roi or None, time.time(), level or ZONE_INSIDE)
        if (roi, level) != self._last_roi:
            if roi:
                # 단계를 남긴다 — 안 보이면 시연 중 "왜 안 잡히지"를 진단할 수 없다.
                self._append_log(f"[HOI] 손 {'진입' if level == ZONE_INSIDE else '접근'}: "
                                 f"{roi} ({'박스 안' if level == ZONE_INSIDE else '링'})")
            self._last_roi = (roi, level)

    def _on_start_process(self):
        self.fsm.load_recipe()
        self._append_log(f"[FSM] 작업 시작 — {self.fsm.expected_step}단계: "
                         f"{self.fsm.current_step_name} ({self.fsm.correct_roi})")
        self._notify("work", "작업 시작",
                     f"{(self._recipe or {}).get('process_name', '기본 시퀀스')} "
                     f"{self.fsm.step_count}단계")

    # =========================================================================
    # [서브 작업] design §5 — 메인 버튼과 다음 버튼 사이에 끼는 작업
    # =========================================================================
    def _press_button(self, button):
        """물리 버튼 눌림(시연: 키보드 1~4·E). 실제로는 GPIO 입력.

        🔑 **정답 버튼이고 서브 작업이 있으면 FSM 에 바로 알리지 않는다.**
           서브 작업을 시작하고, 「다음 단계 진행」에서 비로소 fsm.press_button() 을 부른다.
           그 지연 덕분에 대기 중 다른 버튼을 누르면 기대단계가 아직 안 올라가 있어
           FSM 이 **자동으로 오답 판정**한다 — FSM 을 고칠 필요가 없다(design §5).
        """
        self._append_log(f"[버튼] {button} 눌림")

        # 서브 작업 진행 중이면 어떤 버튼이든 FSM 으로 보낸다 → 오답이면 위반 판정
        if self._sub is not None and self._sub.is_active:
            self._commit_button(button)
            return

        spec = self._sub_spec_for(button)
        if spec is not None and self.fsm.state != State.IDLE and button == self.fsm.correct_roi:
            self._begin_sub(button, spec)
            return

        self._commit_button(button)

    def _commit_button(self, button):
        """FSM 에 실제로 눌림을 전달한다."""
        before = self.fsm.expected_step
        self.fsm.press_button(button, time.time())
        if self.fsm.expected_step != before and self.fsm.state != State.IDLE:
            self._append_log(f"[FSM] 단계 진행 → {self.fsm.expected_step}단계: "
                             f"{self.fsm.current_step_name} ({self.fsm.correct_roi})")
            self._notify("work", f"{before}단계 완료",
                         f"{button} {self._step_name(before)}")

    def _sub_spec_for(self, button):
        """그 버튼 단계의 서브 작업 사양. 없으면 None."""
        for s in (self._recipe or {}).get("steps", []):
            if s.get("button") == button:
                spec = s.get("sub")
                if spec and self._tool_override and spec.get("type") == "wait_tool":
                    spec = dict(spec, tool=self._tool_override)   # 설정에서 바꾼 공구 반영
                return spec
        return None

    def _step_name(self, order):
        for s in (self._recipe or {}).get("steps", []):
            if s.get("order") == order:
                return s.get("name", "")
        return ""

    def _begin_sub(self, button, spec):
        self._sub = SubTask(spec)
        self._sub_button = button
        self._sub_timer.start()
        self._append_log(f"[서브] {spec['label']} 시작 ({spec['sec']}초)")
        self._update_sub_view()

    def _tick_sub(self):
        if self._sub is None or not self._sub.is_active:
            return
        self._sub.tick()
        self._update_sub_view()

    def _update_sub_view(self):
        """게이지·CTA·공구 경고를 서브 작업 상태에 맞춘다."""
        sub = self._sub
        self.gauge_panel.update_view(sub)
        self._relayout()

        if sub is None or not sub.is_active:
            self.btn_cta.hide()
            return

        # 공구 오선택 — 🔴 해제 버튼 없이, 올바른 공구로 바꾸면 스스로 풀린다
        if sub.wrong_tool:
            if self.alert.mode != "tool":
                self.alert.show_wrong_tool(sub.wrong_tool_name, sub.want_tool_name)
                self.glow.set_level("warn")
                self._dim_others(True)
                self._notify("warn", "다른 공구입니다",
                             f"{sub.wrong_tool_name} → {sub.want_tool_name} 필요")
                self._relayout()
        elif self.alert.mode == "tool":
            self.alert.hide_all()
            self.glow.set_level(None)
            self._dim_others(False)

        # 진행 버튼은 조건을 다 채웠을 때만. 표시 여부는 _sync_cta_visibility 가
        # 정한다 — 시트가 열려 있는 동안에는 여기서 되살리면 안 된다(뒤로 비친다).
        if sub.can_advance:
            self.btn_cta.setText("▶  다음 단계 진행")
        self._sync_cta_visibility()

    def _finish_sub(self):
        """「다음 단계 진행」 — 여기서 비로소 FSM 에 눌림을 전달한다."""
        button = self._sub_button
        self._sub_timer.stop()
        self._sub = None
        self._sub_button = None
        self.gauge_panel.update_view(None)
        self.btn_cta.hide()
        if button:
            self._commit_button(button)

    def _on_cta(self):
        """화면 정중앙 버튼 — IDLE 이면 「작업 시작」, 서브 작업 중이면 「다음 단계 진행」."""
        if self._sub is not None and self._sub.is_active:
            self._finish_sub()
        else:
            self._on_start_process()
            self.btn_cta.hide()

    def _on_alert_release(self):
        """경고·차단 배너의 해제 버튼."""
        if self.alert.mode == "block":
            self._release_block()
        elif self.alert.mode == "order":
            self.fsm.release_warning()

    def _release_block(self):
        """BLOCK 해제 버튼 — EMO가 물리적으로 복귀되지 않았으면 거부.

        gpio_input 은 엣지만 발사하므로, 여기서 레벨(emo_active)을 재확인하지
        않으면 EMO 눌림/단선 상태에서도 해제가 통과해 무방비 RUN 이 된다.
        """
        if self.gpio_input.emo_active():
            self._append_log("[FSM] 🚫 BLOCK 해제 거부 — EMO 미복귀(눌림/단선)")
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("해제 거부")
            box.setText("EMO가 아직 복귀되지 않았습니다.\n"
                        "비상정지 버튼을 돌려 복귀(또는 EMO 배선 점검) 후 다시 시도하세요.")
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.setModal(False)
            box.show()
            return
        self.fsm.release_block()

    def keyPressEvent(self, event):
        """시연용 버튼 입력: 1~4 = B1~B4 눌림, E = 비상정지(EMO).

        🔴 ESC = 탈출구 — Full Screen 이라 메뉴가 유일한 출구다(design §7).
           마우스·터치가 안 먹거나 메뉴가 안 열려도 여기로 빠져나온다.
        ⚠️ 오버레이 버튼으로 포커스가 옮겨가면 이 핸들러가 안 불릴 수 있어
           버튼들에 NoFocus 를 준다(_init_ui).
        """
        if event.key() == Qt.Key.Key_Escape:
            # 열려 있는 패널부터 닫는다 — 한 번에 창을 닫지 않는다(오조작 방지)
            # ⚠️ isVisible() 이 아니라 isHidden() 을 본다 — 창이 아직 안 보이는
            #    상태에서는 자식의 isVisible() 이 항상 False 라 이 분기가 통째로 죽는다.
            for panel in (self.settings_panel, self.menu_panel, self.notify_panel):
                if not panel.isHidden():
                    panel.hide()
                    self._dim_others(False)
                    return
            if not self.log_browser.isHidden():
                self._set_log_visible(False)
                return
            self._append_log("[시스템] ESC — 창을 닫습니다")
            self.close()
            return

        key = event.text().upper()
        if key in ("1", "2", "3", "4"):
            self._press_button(f"B{key}")
        elif key == "E":
            self._press_button("EMO")
        else:
            super().keyPressEvent(event)

    # --- FSM 콜백 (GUI 스레드에서 호출됨) ---
    # ※ 상태 색은 theme.py 가 정본이다(StatusPanel 이 토큰으로 고른다).
    #   종전의 _STATE_COLOR 표는 config 의 단일 테마 색을 직접 쓰고 있어 제거했다.

    def _on_fsm_state(self, old, new):
        self.status_panel.update_view(new.value, self.fsm.expected_step)
        self._append_log(f"[FSM] {old.value} → {new.value}")

        # 발광·배너는 상태에 따라 — 🔴 발광은 영상 영역에만(GlowFrame 이 담당)
        if new == State.BLOCK:
            self.glow.set_level("block")
            self.alert.show_block()
            self._dim_others(True)
            self._notify("danger", "전기 입력 차단됨",
                         f"{self.fsm.expected_step}단계 {self.fsm.correct_roi}")
        elif new == State.WARNING:
            self.glow.set_level("warn")
            self.alert.show_order_violation(self.fsm.correct_roi, self.fsm.current_step_name)
            self._dim_others(True)
            self._notify("warn", "순서가 다릅니다",
                         f"지금은 {self.fsm.correct_roi} {self.fsm.current_step_name}")
        else:
            # 공구 경고는 서브 작업 쪽이 관리하므로 그때는 지우지 않는다
            if self.alert.mode != "tool":
                self.glow.set_level(None)
                self.alert.hide_all()
                self._dim_others(False)

        # IDLE 로 돌아오면 다시 「작업 시작」을 띄운다
        if new == State.IDLE:
            self._sub_timer.stop()
            self._sub = None
            self._sub_button = None
            self.gauge_panel.update_view(None)
            self.btn_cta.setText("▶  작업 시작")
            self.btn_cta.show()

        self._relayout()

    def _on_interlock(self, engaged):
        # Arduino Serial 로 릴레이 차단/복구 (트랙 A, interlock.py). BLOCK 진입 시
        # 가장 빠른 차단 경로(engaged=True → 즉시 BLOCK 송신). 해제는 뒤따르는
        # on_feedback(NONE)→RUN 이 처리한다.
        self._append_log(f"[인터록] 전기 신호 {'차단(ON)' if engaged else '복구(OFF)'}")
        self.interlock.set_interlock(engaged)

    def _on_feedback(self, level):
        if level == Feedback.WARNING:
            self._append_log("[피드백] ⚠ 경고 — 시각 팝업 + 청각 타워램프")
        elif level == Feedback.BLOCK:
            self._append_log("[피드백] ⛔ 차단 — 오조작 강행 감지")
        # 램프 명령의 권위 소스 — NONE→RUN / WARNING→WARN / BLOCK→BLOCK 송신.
        self.interlock.set_feedback(level)

    @pyqtSlot(str)
    def _on_interlock_fault(self, msg):
        # BLOCK 명령이 ACK 로 확인되지 않음 — 릴레이가 실제로 안 움직였을 수 있다.
        # 화면 BLOCK 표시만 믿으면 안 되므로 비모달 경고창으로 즉시 알린다.
        self._append_log(f"[인터록] 🚨 폴트: {msg}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("인터락 폴트")
        box.setText("물리 차단이 확인되지 않았습니다!\n"
                    f"{msg}\n\n릴레이·배선·Arduino 전원을 점검하세요.")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.setModal(False)
        box.show()

    # =========================================================================
    # [시스템 종료] — 라즈베리파이 안전 종료(SD 손상 방지). 종료 후 멀티탭 OFF.
    # =========================================================================
    def _on_shutdown_clicked(self):
        # 실수로 눌러 바로 꺼지지 않도록 한 번 더 확인 — '예'를 눌러야만 종료.
        reply = QMessageBox.question(
            self,
            "시스템 종료 확인",
            "라즈베리파이를 안전하게 종료합니다.\n"
            "종료가 완료되면(화면 꺼짐·LED 멈춤) 멀티탭 전원을 내리세요.\n\n"
            "지금 종료할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,   # 기본 선택 = 아니오 (오동작 방지)
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._append_log("[시스템] 종료 취소됨")
            return

        self._append_log("[시스템] 사용자 요청 — 라즈베리파이 안전 종료 시작")
        # 종료 전 안전 정리: 녹화 저장 · 인터락 · 카메라 · 디텍터 해제.
        for step in (
            self._stop_recording,
            self.gpio_input.close,
            self.interlock.close,
            self.camera_thread.stop,
            self.usb_camera_thread.stop,
            close_detector,
        ):
            try:
                step()
            except Exception as e:
                self._append_log(f"[시스템] 정리 중 무시된 오류: {e}")

        try:
            subprocess.Popen(["sudo", "shutdown", "-h", "now"])
        except Exception as e:
            self._append_log(f"[시스템] 종료 명령 실패: {e}")

    # =========================================================================
    # [캘리브레이션]
    # =========================================================================
    @pyqtSlot()
    def _on_calibration_needed(self):
        self._append_log("[캘리브레이션] 필요: 상단 '캘리브레이션' 버튼을 눌러 실행하세요.")

    def _open_calibration_dialog(self):
        dlg = CalibrationDialog(self.camera_thread, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.camera_thread.reload_calibration()
            self._append_log("[캘리브레이션] 완료. 왜곡 보정 재적용.")
        else:
            self._append_log("[캘리브레이션] 취소됨.")

    # =========================================================================
    # [녹화]
    # =========================================================================
    def _start_recording(self, mode="full"):
        """녹화 시작. 🔴 상시 자동이 아니라 **메뉴에서 켤 때만** 돈다.

        mode:
          "full"   — GUI 전체(오버레이 포함). 창을 grab() 하므로 GUI 스레드를 쓴다
          "camera" — 카메라 프레임만. **창 캡처를 안 해 GUI 부담이 거의 0**이다

        코덱은 H.264(.mp4) — config.RECORDING_CODEC. 실측 근거는 config 주석 참조.
        """
        try:
            os.makedirs(RECORDING_SAVE_DIR, exist_ok=True)
            ext = getattr(config, "RECORDING_EXT", "mp4")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._recording_path = os.path.join(
                RECORDING_SAVE_DIR, f"{timestamp}_{mode}.{ext}")
            self._recording_mode = mode

            if mode == "camera":
                size = self._last_frame_size or (640, 480)
            else:
                size = (self.width(), self.height())
            self._recording_size = size

            fourcc = cv2.VideoWriter_fourcc(*RECORDING_CODEC)
            self._video_writer = cv2.VideoWriter(
                self._recording_path, fourcc, RECORDING_FPS, size)
            if not self._video_writer.isOpened():
                self._append_log(f"[녹화] VideoWriter 생성 실패 (코덱 {RECORDING_CODEC})")
                self._video_writer = None
                self._notify("warn", "녹화 시작 실패", f"코덱 {RECORDING_CODEC} 사용 불가")
                return
            self._recording = True
            self._recording_started = time.time()
            if mode == "full":
                self._recording_timer.start()      # 창 캡처는 타이머가 민다
            label = "전체 화면" if mode == "full" else "카메라 영역"
            self._append_log(f"[녹화] {label} 시작 — {self._recording_path}")
            self._notify("work", f"녹화 시작 ({label})", os.path.basename(self._recording_path))
            self.record_panel.set_state(True, self._recording_path, 0)
        except Exception as e:
            self._append_log(f"[녹화] 시작 오류: {e}")

    def _capture_window_frame(self):
        """Full 모드 전용 — 창 전체를 캡처한다. GUI 스레드에서 돈다."""
        if not self._recording or self._video_writer is None:
            return
        if self._recording_mode != "full":
            return
        try:
            pixmap = self.grab()
            qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
            w, h   = qimage.width(), qimage.height()
            ptr    = qimage.bits()
            ptr.setsize(h * w * 3)
            frame = np.array(ptr).reshape(h, w, 3)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            tw, th = self._recording_size
            if frame_bgr.shape[1] != tw or frame_bgr.shape[0] != th:
                frame_bgr = cv2.resize(frame_bgr, (tw, th))
            self._video_writer.write(frame_bgr)
        except Exception as e:
            print(f"[녹화 프레임 오류] {e}")

    def _record_camera_frame(self, frame_bgr):
        """카메라 영역 모드 — 이미 받아 둔 프레임을 그대로 쓴다(창 캡처 없음)."""
        if not self._recording or self._video_writer is None:
            return
        if self._recording_mode != "camera":
            return
        try:
            tw, th = self._recording_size
            if frame_bgr.shape[1] != tw or frame_bgr.shape[0] != th:
                frame_bgr = cv2.resize(frame_bgr, (tw, th))
            self._video_writer.write(frame_bgr)
        except Exception as e:
            print(f"[녹화 프레임 오류] {e}")

    def _stop_recording(self):
        self._recording_timer.stop()
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            self._recording    = False
            size_mb = (os.path.getsize(self._recording_path) / 1024 / 1024
                       if os.path.exists(self._recording_path) else 0)
            self._append_log(f"[녹화] 종료 — {self._recording_path} ({size_mb:.1f} MB)")
            self._notify("work", "녹화 종료",
                         f"{os.path.basename(self._recording_path)} · {size_mb:.1f} MB")
        if hasattr(self, "record_panel"):
            self.record_panel.set_state(False)

    # =========================================================================
    # [종료]
    # =========================================================================
    def closeEvent(self, event):
        self._stop_recording()
        self._append_log("[시스템] 카메라 스레드 종료 중...")
        self.camera_thread.stop()
        self.usb_camera_thread.stop()
        close_detector()
        self.gpio_input.close()
        self.interlock.close()
        event.accept()
