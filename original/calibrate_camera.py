import cv2
import numpy as np
import socket
import struct
import sys
import time

CHESSBOARD = (7, 5)
SAMPLE_COUNT = 20
DETECT_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH |
                cv2.CALIB_CB_NORMALIZE_IMAGE |
                cv2.CALIB_CB_FAST_CHECK)
SAVE_PATH = 'camera_calibration.npz'

ip = sys.argv[1] if len(sys.argv) > 1 else '10.220.25.235'
port = 8888

objp = np.zeros((CHESSBOARD[0] * CHESSBOARD[1], 3), np.float32)
objp[:, :2] = np.mgrid[0:CHESSBOARD[0], 0:CHESSBOARD[1]].T.reshape(-1, 2)

obj_points = []
img_points = []


def recv_exact(sock, length):
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


def recv_frame(sock):
    header = recv_exact(sock, 4)
    length = struct.unpack('<I', header)[0]
    if length == 0 or length > 500000:
        return None
    data = recv_exact(sock, length)
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is not None:
        frame = cv2.flip(frame, 0)
    return frame


print(f"Connecting to {ip}:{port}...")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
sock.settimeout(10)
sock.connect((ip, port))
print("Connected.")
print(f"Show a {CHESSBOARD[0]}x{CHESSBOARD[1]} chessboard to the camera.")
print("Pattern is auto-captured every 1 second when detected. [Q] to quit and calibrate.")

captured = 0
last_capture_time = 0

while captured < SAMPLE_COUNT:
    frame = recv_frame(sock)
    if frame is None:
        continue

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    found, corners = cv2.findChessboardCorners(gray, CHESSBOARD, DETECT_FLAGS)

    display = frame.copy()
    if found:
        corners_refined = cv2.cornerSubPix(
            gray, corners, (11, 11), (-1, -1),
            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        )
        cv2.drawChessboardCorners(display, CHESSBOARD, corners_refined, found)
        cv2.putText(display, "Pattern detected - press SPACE to capture",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    else:
        cv2.putText(display, "No pattern detected",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    cv2.putText(display, f"Captured: {captured}/{SAMPLE_COUNT}",
                (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
    cv2.imshow("Calibration", display)

    key = cv2.waitKey(1) & 0xFF
    now = time.time()

    if found and (now - last_capture_time) > 1.0:
        obj_points.append(objp)
        img_points.append(corners_refined)
        captured += 1
        last_capture_time = now
        print(f"Auto captured {captured}/{SAMPLE_COUNT}")

    if key == ord('q'):
        break

sock.close()
cv2.destroyAllWindows()

if captured < 5:
    print(f"Not enough samples ({captured}). Need at least 5.")
    sys.exit(1)

print(f"\nCalibrating with {captured} samples...")
h, w = frame.shape[:2]
ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
    obj_points, img_points, (w, h), None, None
)

print(f"Calibration RMS error: {ret:.4f} (lower is better, target < 1.0)")
print(f"Camera matrix:\n{camera_matrix}")
print(f"Distortion coefficients:\n{dist_coeffs}")

np.savez(SAVE_PATH, camera_matrix=camera_matrix, dist_coeffs=dist_coeffs,
         image_size=np.array([w, h]))
print(f"\nSaved to {SAVE_PATH}")
