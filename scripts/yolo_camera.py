import cv2
import os
from datetime import datetime
from ultralytics import YOLO

model = YOLO('/home/pi/Downloads/best.pt')

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# 저장 폴더 생성
save_dir = os.path.expanduser('~/Videos/recordings')
os.makedirs(save_dir, exist_ok=True)

# 타임스탬프 기반 파일명
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
video_path = os.path.join(save_dir, f'{timestamp}_recording.avi')
log_path = os.path.join(save_dir, f'{timestamp}_log.txt')

# 녹화 설정
fourcc = cv2.VideoWriter_fourcc(*'XVID')
writer = cv2.VideoWriter(video_path, fourcc, 15.0, (640, 480))

log_file = open(log_path, 'w')
log_file.write('시간,프레임,객체명,신뢰도\n')

print(f"녹화 시작: {video_path}")
print(f"로그 저장: {log_path}")
print("실행 중... 'q' 키로 종료")

frame_count = 0

while True:
    ret, frame = cap.read()
    if not ret:
        print("카메라 프레임 읽기 실패")
        break

    results = model(frame, conf=0.3, verbose=False)
    annotated = results[0].plot()

    # 탐지 결과 로그 기록
    detections = results[0].boxes
    if detections is not None and len(detections) > 0:
        now = datetime.now().strftime('%H:%M:%S')
        for box in detections:
            cls_id = int(box.cls[0])
            cls_name = model.names[cls_id]
            conf = float(box.conf[0])
            log_file.write(f'{now},{frame_count},{cls_name},{conf:.2f}\n')

    writer.write(annotated)
    frame_count += 1

    cv2.imshow('Safety Detection - best.pt', annotated)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
writer.release()
log_file.close()
cv2.destroyAllWindows()

print(f"종료. 녹화 파일: {video_path}")
print(f"로그 파일: {log_path}")
