import os
import time
from datetime import datetime

import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QTextBrowser, QPushButton, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSlot
from PyQt5.QtGui import QImage, QPixmap, QFont

from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT,
    RECORDING_ENABLED, RECORDING_SAVE_DIR, RECORDING_FPS, RECORDING_CODEC,
    FSM_STATES, ROI_THRESHOLD_SEC, BUTTON_ROIS, DEMO_RECIPE,
    CAMERA_TCP_HOST, CAMERA_TCP_PORT,
)
from camera_thread import CameraThread, UsbCameraThread, MEDIAPIPE_AVAILABLE


class SafetyConsole(QMainWindow):
    """
    메인 윈도우.
    - 좌측: ESP32-S3 카메라 영상 (MediaPipe 손 뼈대 + ROI 오버레이)
    - 우측: FSM 상태 라벨 + 단계 표시 + 로그 + 키 안내 + 버튼
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vision AI 안전 콘솔 - ROI 감시 모드")
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        # FSM 변수
        self.current_state     = "IDLE"
        self.recipe            = []
        self.current_step_index = 0

        # 손가락 ROI 감시 변수
        self._current_finger_roi    = ""
        self._monitoring_start_time = None
        self._monitoring_roi_id     = ""

        # 모니터링 타이머 (100ms마다 체류 시간 체크)
        self._monitor_timer = QTimer()
        self._monitor_timer.setInterval(100)
        self._monitor_timer.timeout.connect(self._check_monitoring_timeout)

        # 자동 진행 타이머 (단계 완료 후 1.5초 뒤 자동 진행)
        self._auto_advance_timer = QTimer()
        self._auto_advance_timer.setSingleShot(True)
        self._auto_advance_timer.setInterval(1500)
        self._auto_advance_timer.timeout.connect(self._auto_advance_to_next_step)

        # 녹화 변수
        self._video_writer   = None
        self._recording      = False
        self._recording_path = ""

        # 녹화 타이머
        self._recording_timer = QTimer()
        self._recording_timer.setInterval(int(1000 / RECORDING_FPS))
        self._recording_timer.timeout.connect(self._capture_window_frame)

        self._active_camera = "esp32"

        self._init_ui()

        # 카메라 스레드
        self._last_yolo_classes = set()

        self.camera_thread = CameraThread()
        self.camera_thread.change_pixmap_signal.connect(self._update_camera_frame)
        self.camera_thread.log_signal.connect(self._append_log)
        self.camera_thread.finger_roi_signal.connect(self._on_finger_roi_update)
        self.camera_thread.yolo_detections_signal.connect(self._on_yolo_detections)
        self.camera_thread.start()

        self.usb_camera_thread = UsbCameraThread()
        self.usb_camera_thread.change_pixmap_signal.connect(self._update_usb_frame)
        self.usb_camera_thread.log_signal.connect(self._append_log)
        self.usb_camera_thread.yolo_detections_signal.connect(self._on_yolo_detections)
        self.usb_camera_thread.start()

        # 시작 로그
        self._append_log("[시스템] Vision AI 안전 콘솔 시작 (ROI 감시 모드)")
        self._append_log(f"[시스템] MediaPipe 사용 가능: {MEDIAPIPE_AVAILABLE}")
        self._append_log(f"[시스템] ROI 경고 임계 시간: {ROI_THRESHOLD_SEC}초")
        self._append_log(f"[시스템] ESP32-S3 카메라: {CAMERA_TCP_HOST}:{CAMERA_TCP_PORT} (TCP)")
        self._append_log("─" * 40)
        self._append_log("[ROI 설정] 감시 대상:")
        for roi in BUTTON_ROIS:
            self._append_log(f"  - {roi['label']} ({roi['id']})")
        self._append_log("─" * 40)
        self._append_log("[안내] [S] 작업 시작  →  [G] 확인/진행  →  [5] 리셋")
        self._append_log("─" * 40)

        if RECORDING_ENABLED:
            QTimer.singleShot(500, self._start_recording)

    # =========================================================================
    # [UI 초기화]
    # =========================================================================
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # 왼쪽: 카메라 영상
        self.camera_label = QLabel("카메라 연결 대기 중...")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setStyleSheet(
            "background-color: #1a1a2e; color: #aaaaaa; font-size: 18px;"
            "border: 2px solid #333333; border-radius: 8px;"
        )
        self.camera_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 오른쪽 패널
        right_layout = QVBoxLayout()

        self.state_label = QLabel()
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setFont(QFont("Noto Sans CJK KR", 20, QFont.Bold))
        self.state_label.setFixedHeight(100)
        self._apply_state_style()

        self.step_label = QLabel("작업 대기 중")
        self.step_label.setAlignment(Qt.AlignCenter)
        self.step_label.setFont(QFont("Noto Sans CJK KR", 13))
        self.step_label.setFixedHeight(50)
        self.step_label.setStyleSheet(
            "background-color: #1e3a5f; color: #d4d4d4; border-radius: 6px; padding: 6px;"
        )

        self.log_browser = QTextBrowser()
        self.log_browser.setFont(QFont("Consolas", 10))
        self.log_browser.setStyleSheet(
            "background-color: #0d1117; color: #58a6ff;"
            "border: 1px solid #30363d; border-radius: 6px; padding: 8px;"
        )
        self.log_browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.key_guide_label = QLabel()
        self.key_guide_label.setAlignment(Qt.AlignCenter)
        self.key_guide_label.setFont(QFont("Noto Sans CJK KR", 11))
        self.key_guide_label.setFixedHeight(36)
        self.key_guide_label.setStyleSheet(
            "background-color: #1a1a2e; color: #888888; border-radius: 4px; padding: 4px;"
        )
        self._update_key_guide()

        btn_style = (
            "font-size: 13px; font-weight: bold;"
            "padding: 10px 6px; border-radius: 8px; color: white;"
        )
        self.btn_start   = QPushButton("S 작업 시작")
        self.btn_confirm = QPushButton("G 확인/진행")
        self.btn_reset   = QPushButton("5 리셋")
        self.btn_start.setStyleSheet(btn_style   + "background-color: #e74c3c;")
        self.btn_confirm.setStyleSheet(btn_style + "background-color: #3498db;")
        self.btn_reset.setStyleSheet(btn_style   + "background-color: #e67e22;")
        self.btn_start.clicked.connect(self._on_key_s)
        self.btn_confirm.clicked.connect(self._on_key_g)
        self.btn_reset.clicked.connect(self._on_key_5)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_confirm)
        btn_layout.addWidget(self.btn_reset)

        right_layout.addWidget(self.state_label)
        right_layout.addWidget(self.step_label)
        right_layout.addWidget(self.log_browser)
        right_layout.addWidget(self.key_guide_label)
        right_layout.addLayout(btn_layout)

        self.btn_esp32_cam = QPushButton("초소형카메라")
        self.btn_usb_cam   = QPushButton("CCTV")
        self.btn_esp32_cam.clicked.connect(lambda: self._switch_camera("esp32"))
        self.btn_usb_cam.clicked.connect(lambda: self._switch_camera("usb"))
        self._apply_cam_btn_style()

        cam_btn_layout = QHBoxLayout()
        cam_btn_layout.addWidget(self.btn_esp32_cam)
        cam_btn_layout.addWidget(self.btn_usb_cam)
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
            self.camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.camera_label.setPixmap(QPixmap.fromImage(scaled))

    @pyqtSlot(QImage)
    def _update_usb_frame(self, qt_image):
        if self._active_camera != "usb":
            return
        scaled = qt_image.scaled(
            self.camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
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
        active   = "background-color: #3498db; color: white;"
        inactive = "background-color: #2c2c54; color: #aaaaaa;"
        base     = "font-size: 13px; font-weight: bold; padding: 6px 12px; border-radius: 6px; border: none;"
        self.btn_esp32_cam.setStyleSheet(base + (active if self._active_camera == "esp32" else inactive))
        self.btn_usb_cam.setStyleSheet(base   + (active if self._active_camera == "usb"   else inactive))

    @pyqtSlot(str)
    def _append_log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_browser.append(f"[{timestamp}] {message}")
        self.log_browser.verticalScrollBar().setValue(
            self.log_browser.verticalScrollBar().maximum()
        )

    # =========================================================================
    # [FSM]
    # =========================================================================
    def _change_state(self, new_state):
        old_state = self.current_state
        self.current_state = new_state
        self._apply_state_style()
        info = FSM_STATES[new_state]
        self._append_log(f"[FSM] {old_state} → {new_state} ({info['label']})")
        self._append_log(f"  ↳ {info['description']}")
        self.camera_thread.set_fsm_state(new_state)
        self._update_key_guide()

    def _apply_state_style(self):
        info = FSM_STATES[self.current_state]
        self.state_label.setText(f"{info['label']}\n{self.current_state}")
        self.state_label.setStyleSheet(
            f"background-color: {info['color']};"
            "color: white; border-radius: 10px; padding: 10px;"
        )

    def _update_step_label(self):
        if not self.recipe:
            self.step_label.setText("작업 대기 중")
            self.step_label.setStyleSheet(
                "background-color: #1e3a5f; color: #d4d4d4; border-radius: 6px; padding: 6px;"
            )
            return
        if self.current_step_index >= len(self.recipe):
            self.step_label.setText("모든 단계 완료!")
            self.step_label.setStyleSheet(
                "background-color: #1e5a3a; color: #2ecc71;"
                "border-radius: 6px; padding: 6px; font-weight: bold;"
            )
            return
        step  = self.recipe[self.current_step_index]
        total = len(self.recipe)
        roi_label = self._get_roi_label(step.get("correct_roi", ""))
        self.step_label.setText(f"[{step['step']}/{total}] {step['name']}  →  {roi_label}")
        self.step_label.setStyleSheet(
            "background-color: #1e3a5f; color: #d4d4d4; border-radius: 6px; padding: 6px;"
        )

    def _update_key_guide(self):
        guide_map = {
            "IDLE":          "▶ [S] 작업 시작",
            "RECIPE_LOAD":   "▶ [G] 레시피 확인",
            "RECIPE_LOADED": "▶ [G] 작업 시작",
            "PROCESS_RUN":   "▶ 정답 ROI에 손을 가져가세요 (오답 ROI 접근 시 경고!)",
            "MONITORING":    "▶ 오답 ROI 감시 중... 손을 떼세요!",
            "WARNING":       "▶ 경고! 오답 ROI 체류 초과! 정답 ROI로 이동하세요!",
            "CAUTION":       "▶ 위험 회피됨. 정답 ROI에 손을 가져가세요.",
            "STEP_COMPLETE": "▶ 단계 완료! 다음 단계로 자동 진행 중...",
        }
        text = guide_map.get(self.current_state, "")
        if self.current_state != "IDLE":
            text += "  |  [5] 리셋"
        self.key_guide_label.setText(text)

    def _update_camera_roi(self):
        if self.recipe and self.current_step_index < len(self.recipe):
            step       = self.recipe[self.current_step_index]
            correct_roi = step.get("correct_roi", "")
            active     = self.current_state in ("PROCESS_RUN", "MONITORING", "WARNING", "CAUTION")
            self.camera_thread.set_roi_config(correct_roi, active)
        else:
            self.camera_thread.set_roi_config("", False)

    # =========================================================================
    # [ROI 감시 로직]
    # =========================================================================
    def _get_roi_label(self, roi_id):
        for roi in BUTTON_ROIS:
            if roi["id"] == roi_id:
                return roi["label"]
        return ""

    @pyqtSlot(str)
    def _on_finger_roi_update(self, roi_id):
        if roi_id == self._current_finger_roi:
            return
        self._current_finger_roi = roi_id

        state = self.current_state
        if state not in ("PROCESS_RUN", "MONITORING", "WARNING", "CAUTION"):
            return

        correct_roi = ""
        if self.recipe and self.current_step_index < len(self.recipe):
            correct_roi = self.recipe[self.current_step_index].get("correct_roi", "")

        roi_label = self._get_roi_label(roi_id)

        if state == "PROCESS_RUN":
            if roi_id == correct_roi:
                self._append_log(f"[정답 접근] 정답 ROI '{roi_label}'에 접근 성공!")
                self._auto_complete_step()
            elif roi_id != "":
                self._monitoring_start_time = time.time()
                self._monitoring_roi_id     = roi_id
                self._monitor_timer.start()
                self._append_log(f"[감시 시작] 오답 ROI '{roi_label}' 접근 감지. 감시 중...")
                self._change_state("MONITORING")
                self._update_camera_roi()

        elif state == "MONITORING":
            if roi_id == "":
                elapsed = time.time() - self._monitoring_start_time
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                prev_label = self._get_roi_label(self._monitoring_roi_id)
                self._append_log(
                    f"[필터링] ROI '{prev_label}' 이탈 ({elapsed:.1f}초). Near Miss 기록."
                )
                self._change_state("PROCESS_RUN")
                self._update_camera_roi()
            elif roi_id == correct_roi:
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                self._append_log(f"[교정] 감시 중 정답 ROI '{roi_label}'로 이동 → 행동 교정됨.")
                self._auto_complete_step()
            elif roi_id != self._monitoring_roi_id:
                elapsed = time.time() - self._monitoring_start_time
                prev_label = self._get_roi_label(self._monitoring_roi_id)
                self._monitoring_start_time = time.time()
                self._monitoring_roi_id     = roi_id
                self._append_log(f"[ROI 변경] '{prev_label}' → '{roi_label}' ({elapsed:.1f}초 체류)")

        elif state == "WARNING":
            if roi_id == "":
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                prev_label = self._get_roi_label(self._monitoring_roi_id)
                self._append_log(f"[회피] 경고 후 ROI '{prev_label}'에서 이탈. 위험을 회피했습니다.")
                self._change_state("CAUTION")
                self._update_camera_roi()
            elif roi_id == correct_roi:
                self._monitor_timer.stop()
                self._monitoring_start_time = None
                self._append_log(f"[교정] 경고 중 정답 ROI '{roi_label}'로 이동 → 행동 교정됨.")
                self._auto_complete_step()

        elif state == "CAUTION":
            if roi_id == correct_roi:
                self._append_log(f"[정답 접근] 경계 중 정답 ROI '{roi_label}'에 접근 성공!")
                self._auto_complete_step()
            elif roi_id != "":
                self._monitoring_start_time = time.time()
                self._monitoring_roi_id     = roi_id
                self._monitor_timer.start()
                self._append_log(f"[재진입] 오답 ROI '{roi_label}'에 다시 진입. 감시 재시작.")
                self._change_state("MONITORING")
                self._update_camera_roi()

    def _check_monitoring_timeout(self):
        if self.current_state != "MONITORING" or self._monitoring_start_time is None:
            self._monitor_timer.stop()
            return
        elapsed = time.time() - self._monitoring_start_time
        if elapsed >= ROI_THRESHOLD_SEC:
            self._monitor_timer.stop()
            roi_label = self._get_roi_label(self._monitoring_roi_id)
            self._append_log(
                f"[경고] ROI '{roi_label}' 체류 {elapsed:.1f}초 → 임계값({ROI_THRESHOLD_SEC}초) 초과!"
            )
            self._change_state("WARNING")
            self._update_camera_roi()

    def _auto_complete_step(self):
        self._monitor_timer.stop()
        self._monitoring_start_time = None
        if not self.recipe or self.current_step_index >= len(self.recipe):
            return
        step      = self.recipe[self.current_step_index]
        roi_label = self._get_roi_label(step.get("correct_roi", ""))
        self._append_log(
            f"[정답] 단계 [{step['step']}] '{step['name']}' - 정답 ROI '{roi_label}' 접근 성공!"
        )
        self._change_state("STEP_COMPLETE")
        self._update_camera_roi()
        self._auto_advance_timer.start()

    def _auto_advance_to_next_step(self):
        if self.current_state != "STEP_COMPLETE":
            return
        self.current_step_index += 1
        if self.current_step_index >= len(self.recipe):
            self._append_log("=" * 40)
            self._append_log("[완료] 모든 공정 단계를 성공적으로 완료했습니다!")
            self._append_log("=" * 40)
            self._update_step_label()
            self.camera_thread.set_roi_config("", False)
            self._change_state("IDLE")
            self.recipe = []
            self.current_step_index = 0
        else:
            next_step      = self.recipe[self.current_step_index]
            next_roi_label = self._get_roi_label(next_step.get("correct_roi", ""))
            self._append_log(
                f"[진행] 다음 단계: [{next_step['step']}] {next_step['name']} "
                f"→ 정답 ROI: '{next_roi_label}'"
            )
            self._current_finger_roi = ""
            self._change_state("PROCESS_RUN")
            self._update_step_label()
            self._update_camera_roi()

    # =========================================================================
    # [키 핸들러]
    # =========================================================================
    def _on_key_s(self):
        if self.current_state == "IDLE":
            self._change_state("RECIPE_LOAD")
        else:
            self._append_log(f"[입력 무시] S키는 IDLE 상태에서만 사용 가능. (현재: {self.current_state})")

    def _on_key_g(self):
        state = self.current_state
        if state == "RECIPE_LOAD":
            self.recipe = DEMO_RECIPE.copy()
            self.current_step_index = 0
            self._append_log(f"[레시피] {len(self.recipe)}단계 공정 로드 완료.")
            self._change_state("RECIPE_LOADED")
            self._update_step_label()
        elif state == "RECIPE_LOADED":
            first_step     = self.recipe[self.current_step_index]
            first_roi_label = self._get_roi_label(first_step.get("correct_roi", ""))
            self._append_log(
                f"[시작] 첫 단계: [{first_step['step']}] {first_step['name']} "
                f"→ 정답 ROI: '{first_roi_label}'"
            )
            self._current_finger_roi = ""
            self._change_state("PROCESS_RUN")
            self._update_step_label()
            self._update_camera_roi()
        else:
            self._append_log(f"[입력 무시] G키는 현재 상태에서 사용 불가. (현재: {self.current_state})")

    def _on_key_5(self):
        if self.current_state == "IDLE":
            self._append_log("[리셋] 이미 IDLE 상태입니다.")
            return
        self._append_log("[리셋] 시스템을 초기화합니다...")
        self._monitor_timer.stop()
        self._auto_advance_timer.stop()
        self._monitoring_start_time = None
        self._current_finger_roi    = ""
        self.recipe = []
        self.current_step_index = 0
        self.camera_thread.set_roi_config("", False)
        self._change_state("IDLE")
        self._update_step_label()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_S:
            self._on_key_s()
        elif key == Qt.Key_G:
            self._on_key_g()
        elif key == Qt.Key_5:
            self._on_key_5()

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
            qimage = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
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
    @pyqtSlot(list)
    def _on_yolo_detections(self, detections):
        current = set(d[0] for d in detections)
        if current != self._last_yolo_classes:
            if current:
                self._append_log(f"[YOLO] 탐지: {', '.join(sorted(current))}")
            self._last_yolo_classes = current

    def closeEvent(self, event):
        self._stop_recording()
        self._monitor_timer.stop()
        self._auto_advance_timer.stop()
        self._append_log("[시스템] 카메라 스레드 종료 중...")
        self.camera_thread.stop()
        self.usb_camera_thread.stop()
        event.accept()
