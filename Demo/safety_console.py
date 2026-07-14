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
from PyQt6.QtGui import QImage, QPixmap, QFont

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
from camera_thread import CameraThread, UsbCameraThread, MEDIAPIPE_AVAILABLE, close_detector
from fsm import SafetyFSM, State, Feedback
from recipe import load_recipe, RecipeError
from interlock import InterlockController
from gpio_input import GpioInputController


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
# [단계 흐름 매뉴얼 UI] PRO-7 — 디스플레이에 공정 단계 흐름 + 현재 단계 표시
# =============================================================================
class StepFlowWidget(QWidget):
    """레시피 단계를 세로 흐름으로 표시하고 현재 단계를 강조한다.

    완료(✓) / 현재(▶) / 예정(○) 으로 구분하고, FSM 상태가 WARNING·BLOCK이면
    현재 단계 색을 경고(주황)·차단(빨강)으로 바꾼다. IDLE이면 전체 대기(STANDBY).
    """

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self._steps = steps
        self.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER_COLOR};")

        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(10, 8, 10, 8)

        title = QLabel("공정 단계 매뉴얼")
        title.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ACCENT}; border: none; padding-bottom: 4px;")
        layout.addWidget(title)

        self._rows = []
        for _ in steps:
            row = QLabel()
            row.setWordWrap(True)
            row.setFont(QFont("Consolas", 10))
            layout.addWidget(row)
            self._rows.append(row)
        layout.addStretch()

        self.update_view(1, State.IDLE)

    def update_view(self, expected_step, state):
        started = state != State.IDLE
        # 현재 단계 색은 상태에 따라
        if state == State.WARNING:
            cur_color, cur_mark = STATUS_WARNING, "⚠"
        elif state == State.BLOCK:
            cur_color, cur_mark = STATUS_DANGER, "⛔"
        else:
            cur_color, cur_mark = ACCENT, "▶"

        for i, (s, row) in enumerate(zip(self._steps, self._rows)):
            order = i + 1
            text = f"{s['button']:<4} {s.get('name', '')}"

            if not started:                                  # 대기
                mark, fg, weight, border = "○", TEXT_SECONDARY, "normal", "transparent"
            elif order < expected_step:                      # 완료
                mark, fg, weight, border = "✓", STATUS_OK, "normal", "transparent"
            elif order == expected_step:                     # 현재
                mark, fg, weight, border = cur_mark, cur_color, "bold", cur_color
            else:                                            # 예정
                mark, fg, weight, border = "○", TEXT_SECONDARY, "normal", "transparent"

            row.setText(f"{mark} {text}")
            row.setStyleSheet(
                f"color: {fg}; font-weight: {weight}; border: none;"
                f"border-left: 3px solid {border}; padding: 4px 6px;"
            )


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

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vision AI 안전 콘솔")
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._active_camera = "esp32"
        self._last_yolo_classes = set()
        self._last_roi = ""

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
        self.interlock = InterlockController(
            log=self.bg_log_signal.emit,
            on_fault=self.interlock_fault_signal.emit)

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
        self.camera_thread.start()

        self.usb_camera_thread = UsbCameraThread()
        self.usb_camera_thread.change_pixmap_signal.connect(self._update_usb_frame)
        self.usb_camera_thread.log_signal.connect(self._append_log)
        self.usb_camera_thread.yolo_detections_signal.connect(self._on_yolo_detections)
        self.usb_camera_thread.roi_signal.connect(self._on_roi)
        self.usb_camera_thread.start()

        self._append_log("[시스템] Vision AI 안전 콘솔 시작")
        if self._recipe:
            self._append_log(f"[레시피] '{self._recipe['process_name']}' 로드 — {self.fsm.step_count}단계")
        else:
            self._append_log("[레시피] 파일 없음/오류 — 기본 시퀀스(B1~B4)로 진행")
        self._append_log(f"[시스템] MediaPipe 사용 가능: {MEDIAPIPE_AVAILABLE}")
        self._append_log(f"[시스템] ESP32-S3 카메라: {CAMERA_TCP_HOST}:{CAMERA_TCP_PORT} (TCP)")
        self._append_log(f"[시스템] 로그 저장: {self._log_file_path}")

        if RECORDING_ENABLED:
            QTimer.singleShot(500, self._start_recording)

    # =========================================================================
    # [UI 초기화]
    # =========================================================================
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        self.camera_label = QLabel("카메라 연결 대기 중...")
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setStyleSheet(
            f"background-color: {BG_PANEL}; color: {TEXT_SECONDARY}; font-size: 16px;"
            f"border: 2px solid {BORDER_COLOR};"
        )
        self.camera_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        right_layout = QVBoxLayout()

        self.state_label = QLabel("● STANDBY")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state_label.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        self.state_label.setFixedHeight(80)
        self.state_label.setStyleSheet(
            f"background-color: {BG_PANEL}; color: {STATUS_OK};"
            f"border: 2px solid {STATUS_OK}; padding: 10px; letter-spacing: 2px;"
        )

        self.log_browser = QTextBrowser()
        self.log_browser.setFont(QFont("Consolas", 10))
        self.log_browser.setStyleSheet(
            f"background-color: {BG_LOG}; color: {TEXT_LOG};"
            f"border: 1px solid {BORDER_COLOR}; padding: 8px;"
        )
        self.log_browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # 공정 제어 + 해제 버튼 2종 (해제 버튼은 §9.3: WARNING용/BLOCK용 분리)
        self.btn_start_process = QPushButton("공정 시작 (레시피 로드)")
        self.btn_release_warn  = QPushButton("WARNING 해제")
        self.btn_release_block = QPushButton("BLOCK 해제")
        self.btn_start_process.clicked.connect(self._on_start_process)
        self.btn_release_warn.clicked.connect(lambda: self.fsm.release_warning())
        self.btn_release_block.clicked.connect(lambda: self.fsm.release_block())
        ctrl_base = "font-size: 12px; font-weight: bold; padding: 6px; border-radius: 2px; border: none;"
        self.btn_start_process.setStyleSheet(ctrl_base + f"background-color: {BTN_ACTIVE}; color: {TEXT_PRIMARY};")
        self.btn_release_warn.setStyleSheet(ctrl_base + f"background-color: {STATUS_WARNING}; color: {BG_PRIMARY};")
        self.btn_release_block.setStyleSheet(ctrl_base + f"background-color: {STATUS_DANGER}; color: {TEXT_PRIMARY};")

        release_row = QHBoxLayout()
        release_row.addWidget(self.btn_release_warn)
        release_row.addWidget(self.btn_release_block)

        # 단계 흐름 매뉴얼 (PRO-7) — 레시피 기반. 레시피 없으면 기본 B1~B4로 구성.
        steps = self._recipe["steps"] if self._recipe else [
            {"order": i + 1, "button": f"B{i + 1}", "name": f"{i + 1}단계"}
            for i in range(self.fsm.step_count)
        ]
        self.step_flow = StepFlowWidget(steps)

        right_layout.addWidget(self.state_label)
        right_layout.addWidget(self.step_flow)
        right_layout.addWidget(self.btn_start_process)
        right_layout.addLayout(release_row)
        right_layout.addWidget(self.log_browser, stretch=1)

        self.btn_esp32_cam = QPushButton("초소형카메라")
        self.btn_usb_cam   = QPushButton("CCTV")
        self.btn_calibrate = QPushButton("캘리브레이션")
        self.btn_esp32_cam.clicked.connect(lambda: self._switch_camera("esp32"))
        self.btn_usb_cam.clicked.connect(lambda: self._switch_camera("usb"))
        self.btn_calibrate.clicked.connect(self._open_calibration_dialog)
        self._apply_cam_btn_style()

        # 시스템 종료(라즈베리파이 안전 종료) — 실수 방지 위해 위험색 + 확인창.
        self.btn_shutdown = QPushButton("⏻ 시스템 종료")
        self.btn_shutdown.clicked.connect(self._on_shutdown_clicked)
        self.btn_shutdown.setStyleSheet(
            f"background-color: {BTN_INACTIVE}; color: {STATUS_DANGER};"
            f"border: 2px solid {STATUS_DANGER}; padding: 6px 12px; font-weight: bold;"
        )

        cam_btn_layout = QHBoxLayout()
        cam_btn_layout.addWidget(self.btn_esp32_cam)
        cam_btn_layout.addWidget(self.btn_usb_cam)
        cam_btn_layout.addWidget(self.btn_calibrate)
        cam_btn_layout.addStretch()
        cam_btn_layout.addWidget(self.btn_shutdown)   # 오른쪽 끝에 분리 배치

        cam_panel = QVBoxLayout()
        cam_panel.setSpacing(4)
        cam_panel.addLayout(cam_btn_layout)
        cam_panel.addWidget(self.camera_label)

        main_layout.addLayout(cam_panel, stretch=7)
        main_layout.addLayout(right_layout, stretch=3)

    # =========================================================================
    # [슬롯]
    # =========================================================================
    @pyqtSlot(QImage)
    def _update_camera_frame(self, qt_image):
        if self._active_camera != "esp32":
            return
        scaled = qt_image.scaled(
            self.camera_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.camera_label.setPixmap(QPixmap.fromImage(scaled))

    @pyqtSlot(QImage)
    def _update_usb_frame(self, qt_image):
        if self._active_camera != "usb":
            return
        scaled = qt_image.scaled(
            self.camera_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.camera_label.setPixmap(QPixmap.fromImage(scaled))

    def _switch_camera(self, source):
        self._active_camera = source
        self._apply_cam_btn_style()
        self._last_yolo_classes = set()
        self.camera_thread.set_active(source == "esp32")
        self.usb_camera_thread.set_active(source == "usb")
        label = "초소형카메라 (ESP32-S3)" if source == "esp32" else "CCTV (USB 웹캠)"
        self._append_log(f"[카메라] {label}로 전환")
        if source == "esp32":
            self.camera_label.setText("ESP32-S3 연결 대기 중...")

    def _apply_cam_btn_style(self):
        active   = f"background-color: {BTN_ACTIVE}; color: {TEXT_PRIMARY}; border: 1px solid {ACCENT};"
        inactive = f"background-color: {BTN_INACTIVE}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER_COLOR};"
        calib    = f"background-color: {BTN_CALIB}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER_COLOR};"
        base     = f"font-size: 12px; font-weight: bold; padding: 5px 14px; border-radius: 2px; font-family: Consolas;"
        self.btn_esp32_cam.setStyleSheet(base + (active if self._active_camera == "esp32" else inactive))
        self.btn_usb_cam.setStyleSheet(base   + (active if self._active_camera == "usb"   else inactive))
        self.btn_calibrate.setStyleSheet(base + calib)

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
        if current != self._last_yolo_classes:
            if current:
                self._append_log(f"[YOLO] 탐지: {', '.join(sorted(current))}")
            self._last_yolo_classes = current

    # =========================================================================
    # [판정부 FSM — 인식 입력 / 상태 출력]  통합문서 §8·§9
    # =========================================================================
    @pyqtSlot(str)
    def _on_roi(self, roi):
        """HOI 결과(손끝이 든 버튼 ROI)를 FSM 비전 틱으로 전달."""
        self.fsm.update_vision(roi or None, time.time())
        if roi != self._last_roi:
            if roi:
                self._append_log(f"[HOI] 손 진입: {roi}")
            self._last_roi = roi

    def _on_start_process(self):
        self.fsm.load_recipe()
        self._append_log(f"[FSM] 공정 시작 — {self.fsm.expected_step}단계: "
                         f"{self.fsm.current_step_name} ({self.fsm.correct_roi})")

    def _press_button(self, button):
        """물리 버튼 눌림(시연: 키보드 1~4·E). 실제로는 Arduino Serial 입력."""
        before = self.fsm.expected_step
        self.fsm.press_button(button, time.time())
        self._append_log(f"[버튼] {button} 눌림")
        if self.fsm.expected_step != before and self.fsm.state != State.IDLE:
            self._append_log(f"[FSM] 단계 진행 → {self.fsm.expected_step}단계: "
                             f"{self.fsm.current_step_name} ({self.fsm.correct_roi})")

    def keyPressEvent(self, event):
        """시연용 버튼 입력: 1~4 = B1~B4 눌림, E = 비상정지(EMO)."""
        key = event.text().upper()
        if key in ("1", "2", "3", "4"):
            self._press_button(f"B{key}")
        elif key == "E":
            self._press_button("EMO")
        else:
            super().keyPressEvent(event)

    # --- FSM 콜백 (GUI 스레드에서 호출됨) ---
    _STATE_COLOR = {
        State.IDLE:        STATUS_OK,
        State.READY:       STATUS_OK,
        State.PROCESS_RUN: STATUS_OK,
        State.MONITOR:     ACCENT,
        State.WARNING:     STATUS_WARNING,
        State.BLOCK:       STATUS_DANGER,
    }

    def _on_fsm_state(self, old, new):
        color = self._STATE_COLOR.get(new, TEXT_PRIMARY)
        self.state_label.setText(f"● {new.value}")
        self.state_label.setStyleSheet(
            f"background-color: {BG_PANEL}; color: {color};"
            f"border: 2px solid {color}; padding: 10px; letter-spacing: 2px;"
        )
        self.step_flow.update_view(self.fsm.expected_step, new)
        self._append_log(f"[FSM] {old.value} → {new.value}")

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
    def _start_recording(self):
        try:
            os.makedirs(RECORDING_SAVE_DIR, exist_ok=True)
            timestamp            = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._recording_path = os.path.join(RECORDING_SAVE_DIR, f"{timestamp}_recording.avi")
            fourcc               = cv2.VideoWriter_fourcc(*RECORDING_CODEC)
            self._video_writer   = cv2.VideoWriter(
                self._recording_path, fourcc, RECORDING_FPS, (WINDOW_WIDTH, WINDOW_HEIGHT)
            )
            if self._video_writer.isOpened():
                self._recording = True
                self._recording_timer.start()
                self._append_log(f"[녹화] 시작! 저장 위치: {self._recording_path}")
            else:
                self._append_log("[녹화] VideoWriter 생성 실패!")
                self._video_writer = None
        except Exception as e:
            self._append_log(f"[녹화] 시작 오류: {e}")

    def _capture_window_frame(self):
        if not self._recording or self._video_writer is None:
            return
        try:
            pixmap = self.grab()
            qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
            w, h   = qimage.width(), qimage.height()
            ptr    = qimage.bits()
            ptr.setsize(h * w * 3)
            frame = np.array(ptr).reshape(h, w, 3)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            if frame_bgr.shape[1] != WINDOW_WIDTH or frame_bgr.shape[0] != WINDOW_HEIGHT:
                frame_bgr = cv2.resize(frame_bgr, (WINDOW_WIDTH, WINDOW_HEIGHT))
            self._video_writer.write(frame_bgr)
        except Exception as e:
            print(f"[녹화 프레임 오류] {e}")

    def _stop_recording(self):
        self._recording_timer.stop()
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            self._recording    = False
            self._append_log(f"[녹화] 종료. 저장: {self._recording_path}")

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
