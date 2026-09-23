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

if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
    print("ALL OK")
