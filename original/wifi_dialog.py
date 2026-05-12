import os
import time
import serial
from dotenv import load_dotenv
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QTextEdit, QLabel,
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont

SERIAL_PORT    = "/dev/ttyACM0"
BAUD_RATE      = 115200
CAMERA_IP_FILE = os.path.join(os.path.dirname(__file__), ".camera_ip")


def load_networks():
    load_dotenv()
    networks = []
    i = 1
    while True:
        ssid = os.getenv(f"WIFI_{i}_SSID", "")
        if not ssid:
            break
        password = os.getenv(f"WIFI_{i}_PASSWORD", "")
        networks.append({"ssid": ssid, "password": password})
        i += 1
    return networks


class ProvisionThread(QThread):
    log_signal     = pyqtSignal(str)
    success_signal = pyqtSignal(str)
    fail_signal    = pyqtSignal(str)

    def __init__(self, ssid, password):
        super().__init__()
        self.ssid     = ssid
        self.password = password

    def _open_serial(self):
        return serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=15)

    def run(self):
        try:
            self.log_signal.emit("ESP32 WiFi 초기화 중...")
            ser = self._open_serial()
            ser.write(b"RESET_WIFI\n")
            time.sleep(1)
            ser.close()

            time.sleep(5)

            self.log_signal.emit("새 자격증명 전송 중...")
            ser = self._open_serial()

            deadline = time.time() + 20
            while time.time() < deadline:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self.log_signal.emit(f"ESP32: {line}")
                if "No WiFi credentials" in line or "Send credentials" in line:
                    break

            cmd = f"WIFI:{self.ssid}:{self.password}\n"
            ser.write(cmd.encode())
            self.log_signal.emit(f"SSID [{self.ssid}] 전송 완료. IP 수신 대기 중...")

            camera_ip = None
            deadline = time.time() + 40
            while time.time() < deadline:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    self.log_signal.emit(f"ESP32: {line}")
                if "WiFi connected. IP:" in line:
                    camera_ip = line.split("IP:")[-1].strip()
                    break
                if "Status: WiFi=OK IP=" in line:
                    camera_ip = line.split("IP=")[1].split()[0].strip()
                    break

            ser.close()

            if camera_ip:
                with open(CAMERA_IP_FILE, "w") as f:
                    f.write(camera_ip)
                self.log_signal.emit(f"IP 저장 완료: {camera_ip}")
                self.success_signal.emit(camera_ip)
            else:
                self.fail_signal.emit("ESP32에서 IP를 받지 못했습니다.")

        except serial.SerialException as e:
            self.fail_signal.emit(f"Serial 오류: {e}")
        except Exception as e:
            self.fail_signal.emit(f"오류: {e}")


class WifiDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WiFi 네트워크 선택")
        self.setFixedSize(440, 400)
        self.setStyleSheet("background-color: #16213e; color: white;")
        self.camera_ip        = None
        self._provision_thread = None
        self._networks        = load_networks()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("카메라 TCP 연결 실패\n연결할 WiFi 네트워크를 선택하세요.")
        title.setFont(QFont("Noto Sans CJK KR", 11, QFont.Bold))
        title.setStyleSheet("color: #e74c3c; padding: 6px;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(
            "background-color: #1a1a2e; color: white;"
            "border: 1px solid #333; font-size: 13px; padding: 4px;"
        )
        for net in self._networks:
            label = net["ssid"] + (" (비밀번호 없음)" if not net["password"] else "")
            self.list_widget.addItem(label)
        if self._networks:
            self.list_widget.setCurrentRow(0)
        layout.addWidget(self.list_widget)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedHeight(130)
        self.log_area.setFont(QFont("Consolas", 9))
        self.log_area.setStyleSheet(
            "background-color: #0d1117; color: #58a6ff;"
            "border: 1px solid #30363d; padding: 6px;"
        )
        layout.addWidget(self.log_area)

        btn_layout = QHBoxLayout()
        self.btn_connect = QPushButton("연결")
        self.btn_cancel  = QPushButton("취소")
        self.btn_connect.setStyleSheet(
            "background-color: #2ecc71; color: white;"
            "font-weight: bold; font-size: 13px; padding: 10px; border-radius: 6px;"
        )
        self.btn_cancel.setStyleSheet(
            "background-color: #e74c3c; color: white;"
            "font-size: 13px; padding: 10px; border-radius: 6px;"
        )
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_connect)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def _on_connect(self):
        idx = self.list_widget.currentRow()
        if idx < 0 or idx >= len(self._networks):
            return
        net = self._networks[idx]
        self.btn_connect.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.log_area.clear()
        self.log_area.append(f"[{net['ssid']}] 연결 시작...")

        self._provision_thread = ProvisionThread(net["ssid"], net["password"])
        self._provision_thread.log_signal.connect(self.log_area.append)
        self._provision_thread.success_signal.connect(self._on_success)
        self._provision_thread.fail_signal.connect(self._on_fail)
        self._provision_thread.start()

    def _on_success(self, ip):
        self.camera_ip = ip
        self.log_area.append(f"연결 성공! IP: {ip}")
        self.accept()

    def _on_fail(self, msg):
        self.log_area.append(f"실패: {msg}")
        self.btn_connect.setEnabled(True)
        self.btn_cancel.setEnabled(True)
