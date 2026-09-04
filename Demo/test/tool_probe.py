"""공구 검출 + 서브작업(찾기·쥠) 점검 · 홀드아웃 촬영 도구.

무엇을 답하려고 만들었나 (2026-09-03):
    데모에서 **공구를 쥐었는데도 다음 단계로 넘어가지 않는다.** 그런데 GUI 로그로는
    원인이 넷 중 무엇인지 구별되지 않는다.
        ① 손 자체가 안 잡힘        (hand_tracker 미검출)
        ② 공구가 안 잡힘·오분류    (tool 모델 · conf 미달)
        ③ 손·공구 둘 다 잡혔는데 **검지 끝이 박스 밖**  ← 판정 좌표 문제
        ④ 스캔 주기가 길어 쥔 순간을 놓침
    그래서 스캔마다 이 넷을 **분리해서** 기록한다. 판정 결과 = 통합문서 §10.54.

🔑 검출·촬영 경로는 런타임과 같다 — 같은 ESP32 TCP 수신, 같은 방향·왜곡 보정,
   같은 `hand_tracker`, 같은 `ToolGate`(config 의 conf·주기 그대로),
   같은 `ToolState`·`SubTask`. **판정 규칙을 여기서 바꾸지 않는다** — 지금
   시스템이 무엇을 보고 무엇을 놓치는지 그대로 재는 것이 목적이다.
   🔴 임계·주기·핀 등은 전부 **config 에서 읽는다**(도구 기본값이 config 를 안 따라
      이미 4번 물렸다 — CLAUDE.md 함정).

🔑 `--save-clean` = **홀드아웃 촬영 모드.** 오버레이가 그려지기 **전** 프레임을 PNG 로
   남긴다. 화면·영상에 그려지는 손 랜드마크·공구 박스·HUD 가 든 이미지에 라벨을
   달면 시험지에 답이 인쇄된 것과 같다(설계 = `specs/2026-09-03-공구-쥔상태-검출-design.md` §4).

⚠️ 데모와 **동시에 돌릴 수 없다** — ESP32 스트림도 Hailo 장치도 하나뿐이다.
⚠️ 시스템 파이썬으로 돈다(데모와 같은 환경). 공구 추론만 ToolGate 가 rfenv 워커를
   따로 띄운다 — 이것도 데모와 같다.

쓰는 법:
    python3 Demo/test/tool_probe.py --sec 60 --label B쥠
    python3 Demo/test/tool_probe.py --sec 60 --label wrench_grip \\
            --save-clean ~/holdout/wrench_grip        # 홀드아웃 촬영
"""

import argparse
import datetime
import json
import os
import socket
import struct
import sys
import threading
import time

import cv2
import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)

import config
import frame_orient
from hand_tracker import HandTracker
from sub_task import SubTask
from tool_gate import ToolGate
from tool_state import ToolState

OUT_DIR = os.path.join(config.RECORDING_SAVE_DIR, "공구점검")

# ─────────────────────────────────────────────────────────── 판정 좌표 후보
# MediaPipe 손 랜드마크: 0 손목 / 4 엄지끝 / 8 검지끝 / 12 중지끝 /
#                        5·9·13·17 = 검지·중지·약지·새끼의 뿌리(MCP)
# 공구를 **쥐면** 손가락이 공구를 감싸므로 끝점은 공구 반대편으로 넘어가기 쉽다.
# 반대로 손바닥 중심은 공구 몸통 위에 얹힌다 — 그래서 후보에 넣는다.
# 🔑 판정은 언제나 config 의 규칙(검지 끝)으로 하고, 이 후보들은 **기록만** 한다.
CANDIDATES = {
    "tip8_검지끝(현재)": lambda h: h[8][:2],
    "thumb4_엄지끝":     lambda h: h[4][:2],
    "mid12_중지끝":      lambda h: h[12][:2],
    "mcp9_중지뿌리":     lambda h: h[9][:2],
    "palm_손바닥중심":   lambda h: np.mean(h[[0, 5, 9, 13, 17]][:, :2], axis=0),
    "grip_검지뿌리~중지뿌리": lambda h: np.mean(h[[5, 9]][:, :2], axis=0),
    "hand_21점평균":     lambda h: np.mean(h[:, :2], axis=0),
}
RULE_ANY = "any_21점중_하나라도"
RULE_MAJORITY = "majority_21점중_과반"

_TIP_KEY = "tip8_검지끝(현재)"


def _ts():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _in_box(pt, box):
    x1, y1, x2, y2 = box
    return x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2


def _dist_outside(pt, box):
    """박스 밖으로 얼마나 벗어났나(px). 안이면 0."""
    x1, y1, x2, y2 = box
    dx = max(x1 - pt[0], 0, pt[0] - x2)
    dy = max(y1 - pt[1], 0, pt[1] - y2)
    return float((dx * dx + dy * dy) ** 0.5)


# ────────────────────────────────────────────────────────── ESP32 수신
class Esp32Stream:
    """camera_thread 와 같은 프로토콜(4바이트 LE 길이 + JPEG).

    🔑 밀린 프레임은 버리고 **최신 것만** 쓴다 — 안 그러면 지연이 쌓인다.
    """

    def __init__(self, host, port):
        self._host, self._port = host, port
        self._sock = None
        self._latest = None
        self._running = False
        self._lock = threading.Lock()

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        self._sock.settimeout(config.TCP_RECV_TIMEOUT_SEC)
        self._sock.connect((self._host, self._port))
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = self._sock.recv(n - len(buf))
            except (socket.timeout, OSError):
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    def _loop(self):
        while self._running:
            header = self._recv_exact(4)
            if header is None:
                break
            length = struct.unpack("<I", header)[0]
            if length == 0 or length > config.TCP_MAX_FRAME_BYTES:
                break
            data = self._recv_exact(length)
            if data is None:
                break
            with self._lock:
                self._latest = data
        self._running = False

    def read(self):
        with self._lock:
            data, self._latest = self._latest, None
        if data is None:
            return None
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)

    @property
    def alive(self):
        return self._running

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except Exception:                                     # noqa: BLE001
            pass


def _undistort_map(w, h):
    """camera_thread._load_undistort_map 과 같은 계산(런타임과 동일 보정)."""
    path = config.YOLO_CALIBRATION_PATH
    if not os.path.exists(path):
        return None
    data = np.load(path)
    if "image_size" in data:
        iw, ih = int(data["image_size"][0]), int(data["image_size"][1])
        if (iw, ih) != (w, h):
            return None
    cam_mat, dist = data["camera_matrix"], data["dist_coeffs"]
    new_mat, _ = cv2.getOptimalNewCameraMatrix(cam_mat, dist, (w, h),
                                               config.CALIB_ALPHA, (w, h))
    return cv2.initUndistortRectifyMap(cam_mat, dist, None, new_mat, (w, h), cv2.CV_16SC2)


# ────────────────────────────────────────────────────────────── 본체
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", type=float, default=60.0, help="점검 시간(초)")
    ap.add_argument("--tool", default=None, help="요구 공구(기본: recipe.json 의 wait_tool)")
    ap.add_argument("--label", default="", help="조건 이름 — 파일명에 붙는다(조건 비교용)")
    ap.add_argument("--save-clean", default=None, metavar="디렉터리",
                    help="오버레이 없는 원본 프레임을 PNG 로 저장한다(홀드아웃 촬영용)")
    ap.add_argument("--save-every", type=float, default=1.0, metavar="초",
                    help="원본 프레임 저장 간격(기본 1.0). 연속 프레임은 거의 같은 그림이다")
    args = ap.parse_args()

    # recipe 의 wait_tool 단계를 그대로 쓴다 — 시나리오와 같은 조건으로 재려고.
    with open(os.path.join(_DEMO, "recipe.json")) as f:
        recipe = json.load(f)
    spec = next((s["sub"] for s in recipe["steps"]
                 if s.get("sub", {}).get("type") == "wait_tool"), None)
    if spec is None:
        print("recipe.json 에 wait_tool 단계가 없다")
        return 1
    spec = dict(spec)
    if args.tool:
        spec["tool"] = args.tool
    want = spec["tool"]

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    tag = f"_{args.label}" if args.label else ""
    mp4_path = os.path.join(OUT_DIR, f"{stamp}_tool_probe{tag}.mp4")
    log_path = os.path.join(OUT_DIR, f"{stamp}_tool_probe{tag}.jsonl")
    logf = open(log_path, "w")

    def log(m):
        print(m, flush=True)

    print(f"[설정] want={want}  conf={config.TOOL_CONF}  "
          f"scan={config.TOOL_SCAN_INTERVAL_SEC}s  "
          f"model={os.path.basename(config.TOOL_MODEL_PATH)}  "
          f"sub.sec={spec.get('sec')}  HAND_MIN_SCORE={config.HAND_MIN_SCORE}")
    print(f"[출력] {mp4_path}")

    # 🔴 홀드아웃 촬영용 — **오버레이가 그려지기 전** 프레임을 남긴다.
    clean_dir = None
    if args.save_clean:
        clean_dir = os.path.expanduser(args.save_clean)
        os.makedirs(clean_dir, exist_ok=True)
        print(f"[원본] {clean_dir} 에 {args.save_every}초 간격으로 저장")
    saved, last_save = 0, 0.0

    # 🔴 카메라를 **가장 먼저** 붙인다 — 여기가 가장 흔한 실패 지점이고, 워커·NPU 를
    #    먼저 띄워 두면 연결 실패 때 그것들이 뜬 채로 남는다.
    stream = Esp32Stream(config.CAMERA_TCP_HOST, config.CAMERA_TCP_PORT)
    print(f"[카메라] {config.CAMERA_TCP_HOST}:{config.CAMERA_TCP_PORT} 연결 중...")
    try:
        stream.start()
    except OSError as e:
        logf.close()
        os.remove(log_path)
        print(f"[카메라] 연결 실패: {e}\n"
              f"  · ESP32 전원·배터리와 접속 AP 를 확인할 것(부팅 시점의 AP 를 유지한다).\n"
              f"  · IP 가 바뀌었으면 {os.path.join(_DEMO, '.camera_ip')} 를 고친다.")
        return 1

    hand = HandTracker(log=log)
    gate = ToolGate(log=log)
    gate.start()

    umap = None
    writer = None
    state = ToolState(want)
    sub = None                    # 워커가 준비된 뒤 시작한다(모델 로딩 시간을 안 까먹게)
    scans = []
    tool_dets, tool_dets_at = [], 0.0
    last_scan = 0.0
    t_end = time.time() + args.sec
    frames = 0
    warm = []                     # 녹화 fps 실측용 프레임 시각

    try:
        while time.time() < t_end and stream.alive:
            frame = stream.read()
            if frame is None:
                time.sleep(0.005)
                continue
            now = time.time()
            frames += 1

            # 런타임과 같은 순서: 반전 → 왜곡보정 → 회전
            frame = frame_orient.flip(frame)
            h0, w0 = frame.shape[:2]
            if umap is None:
                umap = _undistort_map(w0, h0) or False
                print(f"[보정] 왜곡보정 {'적용' if umap else '없음(맵 불일치·미존재)'}")
            if umap:
                frame = cv2.remap(frame, umap[0], umap[1], cv2.INTER_LINEAR)
            frame = frame_orient.rotate(frame)

            # 🔴 녹화 fps 는 **실측값**으로 연다 — config.RECORDING_FPS 로 열면 실제
            #    공급이 그보다 느릴 때 영상이 빨라져 「쥔 순간」의 타이밍을 못 잰다.
            warm.append(now)
            if writer is None and len(warm) >= 2 and warm[-1] - warm[0] >= 2.0:
                fps = max(2.0, min(30.0, (len(warm) - 1) / (warm[-1] - warm[0])))
                fh, fw = frame.shape[:2]
                writer = cv2.VideoWriter(
                    mp4_path, cv2.VideoWriter_fourcc(*config.RECORDING_CODEC),
                    fps, (fw, fh))
                print(f"[녹화] {fw}x{fh} @ 실측 {fps:.1f}fps")

            # 🔴 추론에는 오버레이 없는 사본 — 런타임과 같다
            clean = frame.copy()

            # 원본 저장도 **여기서** 한다 — 아래 hand.detect(draw_on=frame) 가
            # frame 에 랜드마크를 직접 그리므로, 그 뒤에 저장하면 오염된다.
            if clean_dir is not None and now - last_save >= args.save_every:
                last_save = now
                cv2.imwrite(os.path.join(clean_dir,
                                         f"{stamp}_{args.label or 'set'}_{saved:04d}.png"), clean)
                saved += 1

            tip = hand.detect(frame, draw_on=frame)
            lms = hand.last_landmarks

            if sub is None and gate.available:
                sub = SubTask(spec)
                print(f"[시작] 워커 준비됨 — 지금부터 {spec.get('sec')}초 타이머 + 공구 판정")
            if sub is not None:
                sub.tick(now)

            # 스캔 요청 — 런타임과 같은 주기. payload 에 랜드마크를 함께 실어 보낸다
            # (ToolGate 는 payload 를 들여다보지 않고 그대로 돌려준다).
            if sub is not None and now - last_scan >= config.TOOL_SCAN_INTERVAL_SEC:
                last_scan = now
                gate.request(clean, (tip, None if lms is None else np.array(lms)))

            got = gate.poll()
            if got is not None:
                dets, payload = got
                r_tip, r_lms = payload
                tool_dets, tool_dets_at = dets, now
                sub.set_tool(state.update(dets, r_tip))
                rec = _record(now, dets, r_tip, r_lms, want, state, sub)
                scans.append(rec)
                logf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                logf.flush()
                print(_line(rec))

            # ── 오버레이 (박스는 런타임처럼 2주기 지나면 지운다)
            if now - tool_dets_at > config.TOOL_SCAN_INTERVAL_SEC * 2:
                tool_dets = []
            _draw(frame, tool_dets, lms, want, state, sub)
            if writer is not None:
                writer.write(frame)
    except KeyboardInterrupt:
        print("\n[중단]")
    finally:
        stream.stop()
        gate.stop()
        hand.close()
        if writer is not None:
            writer.release()
        logf.close()

    if clean_dir is not None:
        print(f"[원본] {saved}장 저장 — {clean_dir}")
    _summary(scans, want, frames, args.sec, mp4_path, log_path)
    return 0


def _record(now, dets, tip, lms, want, state, sub):
    """스캔 한 번의 모든 근거를 남긴다 — 원인 ①②③ 이 여기서 갈린다."""
    want_boxes = [d for d in dets if d[0] == want]
    want_box, want_score = None, None
    if want_boxes:
        b = max(want_boxes, key=lambda d: d[1])        # 점수 최고인 요구 공구
        want_box, want_score = [b[2], b[3], b[4], b[5]], b[1]

    cands = {}
    if lms is not None and want_box is not None:
        for name, fn in CANDIDATES.items():
            pt = [float(v) for v in fn(lms)]
            cands[name] = {"pt": pt, "inside": _in_box(pt, want_box),
                           "out_px": round(_dist_outside(pt, want_box), 1)}
        inside_n = int(sum(1 for p in lms if _in_box(p[:2], want_box)))
        cands[RULE_ANY] = {"inside": inside_n >= 1, "n": inside_n}
        cands[RULE_MAJORITY] = {"inside": inside_n >= 11, "n": inside_n}

    # 원인 분류 — 넘어가지 못한 이 스캔의 책임이 어디인가
    if tip is None:
        cause = "①손_미검출"
    elif want_box is None:
        cause = "②요구공구_미검출"
    elif not cands.get(_TIP_KEY, {}).get("inside"):
        cause = "③검지끝_박스밖"
    else:
        cause = "-"

    return {
        "t": round(now, 3),
        "hand": tip is not None,
        "tip": None if tip is None else [int(tip[0]), int(tip[1])],
        "dets": [[d[0], round(d[1], 3), round(d[2]), round(d[3]), round(d[4]), round(d[5])]
                 for d in dets],
        "want_box": want_box, "want_score": want_score,
        "cause": cause,
        "candidates": cands,
        "phase": state.phase,
        "elapsed": round(sub.elapsed_sec, 2),
        "tool_ok": bool(sub.tool_ok),
        "can_advance": bool(sub.can_advance),
    }


def _line(r):
    names = ",".join(f"{d[0]}:{d[1]:.2f}" for d in r["dets"]) or "-"
    tip = f"({r['tip'][0]},{r['tip'][1]})" if r["tip"] else "손없음"
    tipc = r["candidates"].get(_TIP_KEY)
    extra = ""
    if tipc:
        extra = " 검지끝IN" if tipc["inside"] else f" 검지끝OUT {tipc['out_px']:.0f}px"
    return (f"  {r['elapsed']:5.1f}s  {tip:>12}  [{names}]  {r['cause']:<14}"
            f"{extra}  phase={r['phase']} advance={r['can_advance']}")


def _draw(frame, dets, lms, want, state, sub):
    """표시 전용. 🔴 추론 입력(clean)에는 그리지 않는다."""
    for name, score, x1, y1, x2, y2 in dets:
        c = _box_bgr(name)
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), c,
                      3 if name == want else 1)
        cv2.putText(frame, f"{name} {score:.2f}", (int(x1), max(12, int(y1) - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1, cv2.LINE_AA)
    if lms is not None:
        for label, fn in CANDIDATES.items():
            if label == _TIP_KEY:
                continue                       # 검지끝은 hand_tracker 가 이미 그린다
            pt = fn(lms)
            cv2.circle(frame, (int(pt[0]), int(pt[1])), 5, (255, 200, 0), -1)
            cv2.putText(frame, label.split("_")[0], (int(pt[0]) + 6, int(pt[1])),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 200, 0), 1, cv2.LINE_AA)
    hud = [f"want={want} phase={state.phase}"]
    hud.append(f"t={sub.elapsed_sec:.1f}/{sub.total_sec}s tool_ok={sub.tool_ok} "
               f"advance={sub.can_advance}" if sub is not None else "worker loading...")
    for i, line in enumerate(hud):
        cv2.putText(frame, line, (8, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(frame, line, (8, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)


def _box_bgr(name):
    """config 의 공구 색을 그대로 쓴다 — 도구가 색을 따로 정하지 않는다."""
    hexv = config.TOOL_BOX_COLORS.get(name, config.DETECT_BOX_FALLBACK)
    hexv = hexv.lstrip("#")
    r, g, b = (int(hexv[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


def _summary(scans, want, frames, secs, mp4_path, log_path):
    print("\n" + "=" * 72)
    if not scans:
        print("스캔 결과가 없다 — 워커·카메라 연결을 먼저 확인할 것.")
        print(f"영상: {mp4_path}")
        return
    n = len(scans)
    hand_n = sum(1 for r in scans if r["hand"])
    want_n = sum(1 for r in scans if r["want_box"])
    both = [r for r in scans if r["hand"] and r["want_box"]]
    print(f"프레임 {frames}개 / {secs:.0f}초 (≈{frames / max(secs, 1):.1f}fps),  스캔 {n}회")
    print(f"  손 검출        {hand_n}/{n} ({hand_n / n * 100:.0f}%)")
    print(f"  {want} 검출     {want_n}/{n} ({want_n / n * 100:.0f}%)")
    print("  스캔별 막힌 원인:")
    for cause in ["①손_미검출", "②요구공구_미검출", "③검지끝_박스밖", "-"]:
        c = sum(1 for r in scans if r["cause"] == cause)
        if c:
            print(f"    {cause:<16} {c}/{n} ({c / n * 100:.0f}%)")

    if both:
        print(f"\n  판정 좌표 후보 — 분모 = 손·{want} 둘 다 잡힌 스캔 {len(both)}회")
        print(f"    {'후보':<26}{'박스안':>8}   {'첫 IN 시각':>10}   평균 이탈px")
        t0 = scans[0]["t"]
        for k in list(CANDIDATES) + [RULE_ANY, RULE_MAJORITY]:
            ins = [r for r in both if r["candidates"].get(k, {}).get("inside")]
            first = f"{ins[0]['t'] - t0:.1f}s" if ins else "—"
            outs = [r["candidates"][k]["out_px"] for r in both
                    if "out_px" in r["candidates"].get(k, {})
                    and not r["candidates"][k]["inside"]]
            avg = f"{sum(outs) / len(outs):.0f}" if outs else "-"
            print(f"    {k:<26}{len(ins):>3}/{len(both):<4}{first:>12}   {avg:>8}")
    print(f"\n영상: {mp4_path}\n로그: {log_path}")
    print("=" * 72)


if __name__ == "__main__":
    sys.exit(main())
