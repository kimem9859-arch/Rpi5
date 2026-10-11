"""frame_orient — 해상도별 보정 파일 선택·px_scale (spec 2026-09-23-XGA-런타임전환 §2.2·§2.4)."""
import os, sys, tempfile
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import frame_orient as fo

K = np.array([[500., 0, 320], [0, 500., 240], [0, 0, 1]])
D = np.zeros((1, 5))

def _save(d, name, w, h):
    np.savez(os.path.join(d, name), camera_matrix=K, dist_coeffs=D, image_size=np.array([w, h]))

def test_vga_uses_legacy_file():
    with tempfile.TemporaryDirectory() as d:
        _save(d, "camera_calibration.npz", 640, 480)
        p, st = fo.calibration_path(640, 480, base_dir=d)
        assert st == "ok" and p.endswith("camera_calibration.npz")

def test_xga_prefers_per_resolution():
    with tempfile.TemporaryDirectory() as d:
        _save(d, "camera_calibration.npz", 640, 480)
        _save(d, "camera_calibration_1024x768.npz", 1024, 768)
        p, st = fo.calibration_path(1024, 768, base_dir=d)
        assert st == "ok" and p.endswith("camera_calibration_1024x768.npz")

def test_xga_without_file_is_mismatch():
    with tempfile.TemporaryDirectory() as d:
        _save(d, "camera_calibration.npz", 640, 480)
        assert fo.calibration_path(1024, 768, base_dir=d) == (None, "mismatch")

def test_missing():
    with tempfile.TemporaryDirectory() as d:
        assert fo.calibration_path(640, 480, base_dir=d) == (None, "missing")

def test_per_resolution_size_mismatch():
    with tempfile.TemporaryDirectory() as d:
        _save(d, "camera_calibration_1024x768.npz", 640, 480)   # 이름과 내용이 다름
        assert fo.calibration_path(1024, 768, base_dir=d) == (None, "mismatch")

def test_file_without_image_size_is_not_used():
    """🔴 크기를 모르는 보정 파일은 어느 해상도에서도 쓰지 않는다 — 맞는지 확인할 수 없다."""
    with tempfile.TemporaryDirectory() as d:
        np.savez(os.path.join(d, "camera_calibration.npz"), camera_matrix=K, dist_coeffs=D)
        assert fo.calibration_path(640, 480, base_dir=d) == (None, "mismatch")
        assert fo.calibration_path(1024, 768, base_dir=d) == (None, "mismatch")

def test_load_undistort_returns_path():
    with tempfile.TemporaryDirectory() as d:
        _save(d, "camera_calibration_1024x768.npz", 1024, 768)
        maps, st, p = fo.load_undistort(1024, 768, base_dir=d)
        assert maps is not None and st == "ok" and p.endswith("1024x768.npz")

def test_px_scale():
    assert fo.px_scale(640, 480) == 1.0
    assert fo.px_scale(480, 640) == 1.0          # 회전 뒤에도 같다
    assert fo.px_scale(1024, 768) == 1.6
    assert fo.px_scale(768, 1024) == 1.6

def test_ring_px():
    """링 = VGA 기준 25px × px_scale — 런타임·도구가 같은 식을 쓴다(단일 출처)."""
    import config
    assert fo.ring_px(640, 480) == config.HAND_ROI_RING_PX_VGA
    assert fo.ring_px(768, 1024) == round(config.HAND_ROI_RING_PX_VGA * 1.6)

def _same_as_runtime(img, maps):
    w, h = img.shape[1], img.shape[0]
    old = fo.apply_full(img, maps)
    new = fo.apply_full_map(img, fo.full_map(maps, w, h))
    return old.shape == new.shape and int(np.abs(old.astype(int) - new.astype(int)).max()) == 0


def test_full_map_same_pixels_synthetic():
    """안2 — 합친 맵 한 번 = 반전 → 보정 → 회전과 화소까지 같다(설계 2026-10-12 §3 · 중단 규칙 ①)."""
    maps, st, _ = fo.load_undistort(1024, 768)
    assert maps is not None, st
    rng = np.random.default_rng(0)
    for _ in range(3):
        assert _same_as_runtime(rng.integers(0, 256, (768, 1024, 3), dtype=np.uint8), maps)
    grad = np.dstack([np.tile(np.arange(1024) % 256, (768, 1)).astype(np.uint8)] * 3)
    assert _same_as_runtime(grad, maps)


def test_full_map_same_pixels_real_frames():
    """실제 안경 XGA 원본 30장(있으면) — 없으면 건너뜀."""
    import cv2, glob
    files = sorted(glob.glob(os.path.expanduser("~/lab/화면검사/20261011_②A_뒤/f*.jpg")))[:30]
    if not files:
        print("  원본 프레임 없음 — 건너뜀"); return
    maps, _, _ = fo.load_undistort(1024, 768)
    for p in files:
        assert _same_as_runtime(cv2.imread(p), maps), p


def test_full_map_none_and_flags():
    """맵이 없으면 None(호출부가 종전 반전+회전) · 반전/회전 스위치를 꺼도 같다."""
    import config
    assert fo.full_map(None, 1024, 768) is None
    maps, _, _ = fo.load_undistort(1024, 768)
    img = np.random.default_rng(1).integers(0, 256, (768, 1024, 3), dtype=np.uint8)
    keep = (config.CAMERA_FLIP_VERTICAL, config.CAMERA_ROTATE_CCW90)
    try:
        for fl in (True, False):
            for ro in (True, False):
                config.CAMERA_FLIP_VERTICAL, config.CAMERA_ROTATE_CCW90 = fl, ro
                assert _same_as_runtime(img, maps), (fl, ro)
    finally:
        config.CAMERA_FLIP_VERTICAL, config.CAMERA_ROTATE_CCW90 = keep

def test_full_map_same_pixels_vga():
    """VGA(옛 이름 보정 파일 camera_calibration.npz)도 화소가 같다(최종 리뷰 Minor 3) — 파일이 없으면 None."""
    maps, st, _ = fo.load_undistort(640, 480)
    if maps is None:
        assert fo.full_map(None, 640, 480) is None
        print("  VGA 보정 파일 없음 — 건너뜀", st); return
    rng = np.random.default_rng(2)
    assert _same_as_runtime(rng.integers(0, 256, (480, 640, 3), dtype=np.uint8), maps)
    assert _same_as_runtime(np.full((480, 640, 3), 255, np.uint8), maps)     # 흰 바탕 = 가장자리 0 채움까지

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("ALL OK")
