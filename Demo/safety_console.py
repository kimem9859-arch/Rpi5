import os
import time
from datetime import datetime

import cv2
import numpy as np
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QTextBrowser, QPushButton, QSizePolicy,
    QDialog, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot
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
from camera_thread import CameraThread, UsbCameraThread, MEDIAPIPE_AVAILABLE


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

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vision AI 안전 콘솔")
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._active_camera = "esp32"
        self._last_yolo_classes = set()

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

        self.camera_thread = CameraThread()
        self.camera_thread.change_pixmap_signal.connect(self._update_camera_frame)
        self.camera_thread.log_signal.connect(self._append_log)
        self.camera_thread.yolo_detections_signal.connect(self._on_yolo_detections)
        self.camera_thread.calibration_needed_signal.connect(self._on_calibration_needed)
        self.camera_thread.start()

        self.usb_camera_thread = UsbCameraThread()
        self.usb_camera_thread.change_pixmap_signal.connect(self._update_usb_frame)
        self.usb_camera_thread.log_signal.connect(self._append_log)
        self.usb_camera_thread.yolo_detections_signal.connect(self._on_yolo_detections)
        self.usb_camera_thread.start()

        self._append_log("[시스템] Vision AI 안전 콘솔 시작")
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

        right_layout.addWidget(self.state_label)
        right_layout.addWidget(self.log_browser)

        self.btn_esp32_cam = QPushButton("초소형카메라")
        self.btn_usb_cam   = QPushButton("CCTV")
        self.btn_calibrate = QPushButton("캘리브레이션")
        self.btn_esp32_cam.clicked.connect(lambda: self._switch_camera("esp32"))
        self.btn_usb_cam.clicked.connect(lambda: self._switch_camera("usb"))
        self.btn_calibrate.clicked.connect(self._open_calibration_dialog)
        self._apply_cam_btn_style()

        cam_btn_layout = QHBoxLayout()
        cam_btn_layout.addWidget(self.btn_esp32_cam)
        cam_btn_layout.addWidget(self.btn_usb_cam)
        cam_btn_layout.addWidget(self.btn_calibrate)
        cam_btn_layout.addStretch()

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
        event.accept()
