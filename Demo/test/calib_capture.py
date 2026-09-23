"""카메라 캘리브레이션 촬영·계산 — 해상도별 보정 파일을 «따로» 만든다.

왜 GUI 의 CalibrationDialog 를 쓰지 않나 (2026-09-23 · 상위 §12.68):
    ① 그 창은 `camera_calibration.npz` 를 **덮어쓴다** — XGA 파일을 만들면 VGA 런타임이 깨진다.
    ② 그 창은 **상하 반전 전** 프레임으로 계산하는데 런타임은 **반전 → 왜곡보정 → 회전** 순서로
       적용한다. 반전 전 값을 반전된 그림에 쓰면 렌즈 중심(cy)이 위아래로 어긋난다.
       이 도구는 **반전한 뒤** 코너를 찾는다 — 보정이 적용되는 지점과 같은 그림이다.
    ③ 그 창은 자세 다양성을 보지 않는다 — 같은 자세 20장이면 보정이 부정확해진다.

쓰는 법:
    DISPLAY=:0 python3 test/calib_capture.py            # 촬영 + 계산 (파이 모니터에 체스보드 전체화면)
    python3 test/calib_capture.py --from-dir <샘플폴더>   # 저장된 샘플로 다시 계산만
    python3 test/calib_capture.py --self-test             # chessboard.png 로 코너 검출 점검

체스보드·검출 설정(7×5 · 플래그 · cornerSubPix)은 CalibrationDialog 와 같다 — 결과를 비교할 수 있게.
"""
import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_DEMO_DIR = os.path.dirname(_TEST_DIR)
sys.path.insert(0, _DEMO_DIR)
sys.path.insert(0, _TEST_DIR)

import config          # noqa: E402
import frame_orient    # noqa: E402

CHESSBOARD = (7, 5)    # 내부 코너 — safety_console.CalibrationDialog 와 같다
DETECT_FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK)
SUBPIX = ((11, 11), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001))
BOARD_PNG = os.path.join(_DEMO_DIR, "chessboard.png")
RMS_GOAL = 0.5         # px — 합격 기준(설계에서 측정 전에 정함)
WIN = "calib_board"


def find_corners(bgr):
    gray = cv2.equalizeHist(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    found, corners = cv2.findChessboardCorners(gray, CHESSBOARD, DETECT_FLAGS)
    if not found:
        return None
    return cv2.cornerSubPix(gray, corners, *SUBPIX)


def pose_of(corners, w):
    """자세 요약 — 중심(화면 폭 비율) · 넓이 비율 · 기울기(도)."""
    pts = corners.reshape(-1, 2)
    cx, cy = pts.mean(axis=0) / w
    area = cv2.contourArea(cv2.convexHull(pts.astype(np.float32))) / (w * w)
    row = pts[CHESSBOARD[0] - 1] - pts[0]          # 첫 줄의 방향
    ang = float(np.degrees(np.arctan2(row[1], row[0])))
    return float(cx), float(cy), float(area), ang


def is_new_pose(p, poses, min_move, min_area, min_tilt):
    """이미 받은 자세들과 충분히 다른가 — 위치·크기·기울기 중 하나라도."""
    for q in poses:
        moved = ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5 >= min_move
        scaled = abs(p[2] - q[2]) / max(q[2], 1e-6) >= min_area
        tilted = abs(p[3] - q[3]) >= min_tilt
        if not (moved or scaled or tilted):
            return False
    return True


FONT_PATH = "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf"
GUIDE = "팔꿈치를 책상에 대고 최대한 가만히  ·  체스보드가 카메라 화면 절반 이상  ·  화면 가장자리·모서리 쪽에도  ·  기울여서도"
TOP = 190              # 위쪽 글자 영역(px) — 체스보드는 그 아래에 그린다


def board_canvas(sw, sh, text, sub=""):
    """체스보드를 모니터에 크게 — 위쪽에 진행·상태·안내.

    🔴 글자는 Pillow + 한글 글꼴로 그린다 — cv2.putText 는 한글을 `???` 로 찍는다(2026-09-23 실제로 발생).
    """
    from PIL import Image, ImageDraw, ImageFont
    board = cv2.imread(BOARD_PNG)
    canvas = np.full((sh, sw, 3), 255, np.uint8)
    s = min((sw - 80) / board.shape[1], (sh - TOP - 30) / board.shape[0])
    b = cv2.resize(board, (int(board.shape[1] * s), int(board.shape[0] * s)), interpolation=cv2.INTER_NEAREST)
    y0, x0 = TOP + (sh - TOP - b.shape[0]) // 2, (sw - b.shape[1]) // 2
    canvas[y0:y0 + b.shape[0], x0:x0 + b.shape[1]] = b
    img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)
    d.text((24, 12), text, font=ImageFont.truetype(FONT_PATH, 64), fill=(200, 0, 0))
    if sub:
        d.text((260, 26), sub, font=ImageFont.truetype(FONT_PATH, 40), fill=(20, 20, 20))
    d.text((24, 110), GUIDE, font=ImageFont.truetype(FONT_PATH, 30), fill=(90, 90, 90))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


GUIDE_EXT = "카메라는 고정  ·  노트북을 옮기거나 기울인 뒤 손을 떼세요  ·  초록 테두리가 없는 곳(특히 가장자리·모서리)을 채우세요  ·  기울인 자세도"


def preview_canvas(sw, sh, frame, corners, hulls, text, sub=""):
    """외부 체스보드(노트북 화면 등)를 찍을 때 — 파이 모니터에 카메라 화면을 보여 준다.

    코너를 찾으면 점을, 이미 저장한 자세는 초록 테두리로 그려 **비어 있는 곳**이 보이게 한다.
    검출·저장은 반전만 한 그림(런타임 보정 적용 지점)으로 하고, 화면에만 회전을 적용해 사람이 보기 편하게 한다.
    """
    from PIL import Image, ImageDraw, ImageFont
    vis = frame.copy()
    for hpts in hulls:
        cv2.polylines(vis, [hpts.astype(np.int32)], True, (0, 200, 0), 3)
    if corners is not None:
        cv2.drawChessboardCorners(vis, CHESSBOARD, corners, True)
    vis = frame_orient.rotate(vis)
    s = min((sw - 40) / vis.shape[1], (sh - TOP - 20) / vis.shape[0])
    vis = cv2.resize(vis, (int(vis.shape[1] * s), int(vis.shape[0] * s)))
    canvas = np.full((sh, sw, 3), 255, np.uint8)
    y0, x0 = TOP + (sh - TOP - vis.shape[0]) // 2, (sw - vis.shape[1]) // 2
    canvas[y0:y0 + vis.shape[0], x0:x0 + vis.shape[1]] = vis
    img = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(img)
    d.text((24, 12), text, font=ImageFont.truetype(FONT_PATH, 64), fill=(200, 0, 0))
    if sub:
        d.text((260, 26), sub, font=ImageFont.truetype(FONT_PATH, 40), fill=(20, 20, 20))
    d.text((24, 110), GUIDE_EXT, font=ImageFont.truetype(FONT_PATH, 30), fill=(90, 90, 90))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def calibrate(obj_pts, img_pts, size):
    rms, K, D, rvecs, tvecs = cv2.calibrateCamera(obj_pts, img_pts, size, None, None)
    errs = []
    for o, i, r, t in zip(obj_pts, img_pts, rvecs, tvecs):
        proj, _ = cv2.projectPoints(o, r, t, K, D)
        errs.append(float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - i.reshape(-1, 2)) ** 2, axis=1)))))
    return rms, K, D, errs


def solve(samples, size, out_path, meta):
    """계산 → 튀는 장 제거 → 저장 → 기존 VGA 값과 비교."""
    if os.path.abspath(out_path) == os.path.abspath(config.YOLO_CALIBRATION_PATH):
        raise SystemExit(f"🔴 런타임 보정 파일({out_path})은 덮어쓰지 않는다 — --out 을 바꿀 것")
    objp = np.zeros((CHESSBOARD[0] * CHESSBOARD[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHESSBOARD[0], 0:CHESSBOARD[1]].T.reshape(-1, 2)
    names = [n for n, _ in samples]
    img_pts = [c for _, c in samples]
    keep = list(range(len(samples)))
    rms, K, D, errs = calibrate([objp] * len(keep), img_pts, size)
    print(f"\n[계산] {len(keep)}장 · RMS {rms:.4f}px")
    # 튀는 장 제거 — **기본은 끔**. 가장자리 샘플은 원래 오차가 조금 커서, 이 규칙을 켜면 가장자리 정보부터
    # 빠진다(2026-09-23 실측: 34장 중 가장자리 보충 3장이 빠져 가장 먼 코너가 줄었다). 켜려면 meta["drop"]=True.
    med = float(np.median(errs))
    drop = [k for k, e in zip(keep, errs) if e > 2 * med] if meta.get("drop") else []
    if drop and len(keep) - len(drop) >= 15:
        print(f"  튀는 장 {len(drop)}개 제외: " + ", ".join(f"{names[k]}({errs[keep.index(k)]:.2f})" for k in drop))
        keep = [k for k in keep if k not in drop]
        rms, K, D, errs = calibrate([objp] * len(keep), [img_pts[k] for k in keep], size)
        print(f"[재계산] {len(keep)}장 · RMS {rms:.4f}px")
    verdict = "✅ 합격" if rms <= RMS_GOAL else "🔴 불합격"
    print(f"  {verdict} (기준 {RMS_GOAL}px) · 장별 오차 median {np.median(errs):.3f} · max {max(errs):.3f}")
    w, h = size
    meta.update(rms=float(rms), n_used=len(keep), n_captured=len(samples), flipped=True,
                used=[names[k] for k in keep], created=datetime.now().isoformat(timespec="seconds"))
    np.savez(out_path, camera_matrix=K, dist_coeffs=D, image_size=np.array([w, h]),
             meta=json.dumps(meta, ensure_ascii=False))
    print(f"  저장: {out_path}")
    print(f"  fx {K[0,0]:.1f} · fy {K[1,1]:.1f} · cx {K[0,2]:.1f} · cy {K[1,2]:.1f} · dist {np.round(D.ravel(), 4).tolist()}")
    allp = np.vstack([img_pts[k].reshape(-1, 2) for k in keep])
    rmax = float(np.hypot(allp[:, 0] - K[0, 2], allp[:, 1] - K[1, 2]).max())
    rcorner = float(np.hypot(max(K[0, 2], w - K[0, 2]), max(K[1, 2], h - K[1, 2])))
    print(f"  덮은 범위 — 중심에서 가장 먼 코너 {rmax:.0f}px / 화면 모서리 {rcorner:.0f}px = {100 * rmax / rcorner:.0f}% "
          f"(그 바깥은 추정)")
    # 참고 — 기존 VGA 파일(반전 전 계산)을 이 해상도로 늘렸을 때
    vga = os.path.join(_DEMO_DIR, "camera_calibration.npz")
    if os.path.exists(vga):
        v = np.load(vga)
        vw, vh = (int(x) for x in v["image_size"])
        s = w / vw
        vk = v["camera_matrix"]
        print(f"  [참고] 기존 VGA×{s:.2f} — fx {vk[0,0]*s:.1f} · fy {vk[1,1]*s:.1f} · cx {vk[0,2]*s:.1f} · "
              f"cy {vk[1,2]*s:.1f} (반전을 반영하면 {(vh - 1 - vk[1,2])*s:.1f})")
    return rms <= RMS_GOAL


def save_check_image(sample_png, out_path, size):
    """보정 전·후 나란히 — 직선이 펴지는지 눈으로 본다."""
    data = np.load(out_path)
    K, D = data["camera_matrix"], data["dist_coeffs"]
    img = cv2.imread(sample_png)
    newK, _ = cv2.getOptimalNewCameraMatrix(K, D, size, config.CALIB_ALPHA, size)
    und = cv2.undistort(img, K, D, None, newK)
    both = np.hstack([img, np.full((img.shape[0], 8, 3), 255, np.uint8), und])
    p = os.path.splitext(out_path)[0] + "_check.png"
    cv2.imwrite(p, both)
    print(f"  보정 전·후 비교: {p}")


def capture(args):
    from bench_detector import _connect_tcp, _recv_latest_frame   # 수신은 기존 도구와 같은 경로
    host = args.host or config.CAMERA_TCP_HOST
    sock = _connect_tcp(host)
    if sock is None:
        return 1
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sample_dir = args.add_to or os.path.join(_TEST_DIR, "raw", f"{stamp}_calib")
    os.makedirs(sample_dir, exist_ok=True)
    cv2.namedWindow(WIN, cv2.WND_PROP_FULLSCREEN)
    cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    sw, sh = args.screen
    samples, poses, size = [], [], None
    prev_c = None                                   # 직전 프레임 코너 — 멈춤 판정
    still_buf = []                                  # 멈춘 채로 이어진 프레임들의 코너 — 평균해 저장
    last_t, status = 0.0, "카메라를 체스보드에 비추세요"
    hulls = []                                      # 저장한 자세의 테두리 — 외부 체스보드 방식에서 빈 곳을 보여 준다
    n_before = 0
    if args.add_to:                                 # 기존 샘플에 이어 찍기 — 빈 곳(가장자리)을 보충한다
        for png in sorted(glob.glob(os.path.join(sample_dir, "s*.png"))):
            c0 = np.load(png.replace(".png", "_corners.npy")).astype(np.float32)
            samples.append((os.path.basename(png), c0))
            poses.append(pose_of(c0, cv2.imread(png).shape[1]))
            hulls.append(cv2.convexHull(c0.reshape(-1, 2)).reshape(-1, 2))
        n_before = len(samples)
        print(f"[이어 찍기] 기존 {n_before}장 불러옴 — {sample_dir}")
    ext = args.board == "external"
    if not ext:
        cv2.imshow(WIN, board_canvas(sw, sh, f"0 / {args.samples}", status))
        cv2.waitKey(1)
    target = n_before + args.samples if args.add_to else args.samples
    while len(samples) < target:
        data = _recv_latest_frame(sock)
        if data is None:
            print("[TCP] 수신 끊김"); break
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        frame = frame_orient.flip(frame)          # 🔴 런타임이 보정을 적용하는 지점과 같은 그림
        h, w = frame.shape[:2]
        if size is None:
            size = (w, h)
            print(f"[프레임] {w}×{h} · 반전 적용")
        c = find_corners(frame)
        now = time.time()
        # 🔴 손 떨림 차단 — 센서가 한 장을 약 36ms 에 걸쳐 줄 단위로 읽어(롤링 셔터) 그사이 움직이면
        #    사진이 불규칙하게 일그러진다. 2026-09-23 첫 촬영은 손에 들고 찍어 평면 맞춤 오차가 1.7px 였다.
        still = None
        if c is not None and prev_c is not None and c.shape == prev_c.shape:
            still = float(np.mean(np.linalg.norm((c - prev_c).reshape(-1, 2), axis=1)))
        prev_c = c
        if c is not None and still is not None and still <= args.still_px:
            still_buf.append(c)
        else:
            still_buf = [c] if c is not None else []
        if c is None:
            status = "체스보드를 찾는 중..."
        elif now - last_t < args.interval:
            pass
        elif still is None or still > args.still_px:
            status = (f"움직이는 중 — 멈출 때까지 기다리는 중 (흔들림 {still if still is not None else 0:.1f}px)" if ext
                      else f"움직이는 중 — 카메라를 멈춰 주세요 (흔들림 {still if still is not None else 0:.1f}px)")
        elif len(still_buf) < args.avg:
            status = f"멈춤 확인 중... ({len(still_buf)}/{args.avg})"
        else:
            # 🔑 연속 N장 평균 — 매 장 제각각 흔들린 몫이 평균되며 줄어든다(2026-09-23: 멈춘 순간만 골라도 0.7~1.1px)
            c = np.mean(np.stack(still_buf[-args.avg:]), axis=0).astype(np.float32)
            p = pose_of(c, w)
            if poses and not is_new_pose(p, poses, args.min_move, args.min_area, args.min_tilt):
                status = "비슷한 자세 — 각도·거리·위치를 바꿔 주세요"
            else:
                name = f"s{len(samples)+1:02d}.png"
                cv2.imwrite(os.path.join(sample_dir, name), frame)
                np.save(os.path.join(sample_dir, name.replace(".png", "_corners.npy")), c)
                samples.append((name, c)); poses.append(p); last_t = now
                hulls.append(cv2.convexHull(c.reshape(-1, 2)).reshape(-1, 2))
                status = f"저장됨 — 다른 자세로 (중심 {p[0]:.2f},{p[1]:.2f} · 넓이 {p[2]:.3f} · 흔들림 {still:.2f}px)"
                print(f"  [{len(samples):2d}/{target}] {name} · {status}")
        if ext:
            cv2.imshow(WIN, preview_canvas(sw, sh, frame, c, hulls, f"{len(samples)} / {target}", status))
        else:
            cv2.imshow(WIN, board_canvas(sw, sh, f"{len(samples)} / {target}", status))
        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            print("중단(q)"); break
    sock.close()
    cv2.destroyAllWindows()
    if len(samples) < 10 or size is None:
        print(f"🔴 샘플 {len(samples)}장 — 계산하지 않는다(최소 10). 샘플: {sample_dir}")
        return 1
    out = args.out or os.path.join(_DEMO_DIR, f"camera_calibration_{size[0]}x{size[1]}.npz")
    ok = solve(samples, size, out, {"source": "calib_capture", "sample_dir": sample_dir, "host": host, "drop": args.drop_outliers})
    save_check_image(os.path.join(sample_dir, samples[0][0]), out, size)
    print(f"샘플 보존: {sample_dir}")
    return 0 if ok else 2


def from_dir(args):
    d = args.from_dir
    pngs = sorted(glob.glob(os.path.join(d, "s*.png")))
    samples = [(os.path.basename(p), np.load(p.replace(".png", "_corners.npy"))) for p in pngs]
    h, w = cv2.imread(pngs[0]).shape[:2]
    out = args.out or os.path.join(_DEMO_DIR, f"camera_calibration_{w}x{h}.npz")
    ok = solve(samples, (w, h), out, {"source": "calib_capture --from-dir", "sample_dir": d, "drop": args.drop_outliers})
    save_check_image(pngs[0], out, (w, h))
    return 0 if ok else 2


def make_board(W, H, out=None):
    """외부 화면용 체스보드 — 8×6 칸(내부 코너 7×5), 칸 크기를 정수로 같게, 가장자리 흰 여백 한 칸 이상."""
    sq = min(W // 10, H // 8)                       # 여백 포함 가로 10칸·세로 8칸이 들어가는 가장 큰 정수 칸
    img = np.full((H, W), 255, np.uint8)
    bw, bh = 8 * sq, 6 * sq
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    for r in range(6):
        for c in range(8):
            if (r + c) % 2 == 0:
                img[y0 + r * sq:y0 + (r + 1) * sq, x0 + c * sq:x0 + (c + 1) * sq] = 0
    out = out or os.path.join(_TEST_DIR, f"chessboard_{W}x{H}.png")
    cv2.imwrite(out, img)
    ok = find_corners(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)) is not None
    print(f"체스보드 {W}×{H} · 칸 {sq}px · 7×5 코너 {'✅' if ok else '🔴'} → {out}")
    return 0 if ok else 1


def self_test():
    board = cv2.imread(BOARD_PNG)
    c = find_corners(board)
    print(f"chessboard.png {board.shape[1]}×{board.shape[0]} · 7×5 코너 {'✅ 검출' if c is not None else '🔴 실패'}")
    if c is not None:
        p = pose_of(c, board.shape[1])
        print(f"  자세 = 중심 ({p[0]:.2f},{p[1]:.2f}) · 넓이 {p[2]:.3f} · 기울기 {p[3]:.1f}°")
        # 다양성 판정 점검 — 같은 자세는 거절, 옮긴 자세는 통과해야 한다
        assert not is_new_pose(p, [p], 0.08, 0.25, 8), "같은 자세를 새 자세로 받았다"
        assert is_new_pose((p[0] + 0.2, p[1], p[2], p[3]), [p], 0.08, 0.25, 8), "옮긴 자세를 거절했다"
        print("  다양성 판정 ✅")
    return 0 if c is not None else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--interval", type=float, default=1.0, help="샘플 사이 최소 간격(초)")
    ap.add_argument("--min-move", type=float, default=0.08, help="중심 이동(화면 폭 비율)")
    ap.add_argument("--min-area", type=float, default=0.25, help="넓이 변화 비율")
    ap.add_argument("--min-tilt", type=float, default=8.0, help="기울기 변화(도)")
    ap.add_argument("--avg", type=int, default=3, help="멈춘 상태로 연속한 N장의 코너를 평균해 저장(손 떨림 몫을 줄인다)")
    ap.add_argument("--still-px", type=float, default=0.5, help="직전 프레임과 코너 평균 차이가 이 값 이하일 때만 저장(카메라가 멈춘 순간)")
    ap.add_argument("--board", choices=["monitor", "external"], default="monitor",
                    help="monitor = 파이 모니터에 체스보드 표시(손으로 카메라를 듦) · external = 체스보드는 노트북 등 다른 화면·종이, 파이 모니터엔 카메라 화면")
    ap.add_argument("--make-board", type=int, nargs=2, metavar=("W", "H"), default=None,
                    help="외부 화면용 체스보드 PNG 를 만든다(칸 크기가 정수로 같게) — 예: --make-board 1920 1080")
    ap.add_argument("--screen", type=int, nargs=2, default=(1920, 1280), metavar=("W", "H"))
    ap.add_argument("--host", default=None)
    ap.add_argument("--out", default=None, help="기본 = Demo/camera_calibration_<W>x<H>.npz (기존 파일을 덮어쓰지 않는다)")
    ap.add_argument("--from-dir", default=None)
    ap.add_argument("--drop-outliers", action="store_true", help="오차가 중앙값의 2배를 넘는 장을 빼고 다시 계산(기본 끔 — 가장자리 정보가 먼저 빠진다)")
    ap.add_argument("--add-to", default=None, metavar="샘플폴더", help="기존 샘플 폴더에 이어 찍고 전체로 다시 계산(--samples 는 추가할 장수)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.make_board:
        return make_board(*args.make_board, args.out)
    if args.from_dir:
        return from_dir(args)
    return capture(args)


if __name__ == "__main__":
    sys.exit(main())
