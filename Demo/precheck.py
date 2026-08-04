"""점검 — 1차(기동)·2차(작업 시작)·수동(메뉴) 세 갈래가 **같은 규칙**을 쓴다.

정본: 상위 `docs/superpowers/specs/2026-08-03-uiux-글라스-design.md` §4.2

왜 한 곳에 모으나:
    같은 항목을 세 군데서 각각 판정하면 **규칙이 갈라진다.** `dwell_probe` 가
    config 를 안 따라 네 번 물렸던 전례가 있다. 여기가 단일 출처다.

두 점검은 묻는 것이 다르다:
    1차 = **"부품이 다 있나"** (연결·로드). 기동 시 백그라운드로 한 번.
    2차 = **"지금 실제로 되나"** (동작). 작업 시작 때마다.
    수동 = 아무 때나 다시 확인·재연결 (메뉴 → 점검(연결)).

⚠️ Qt 에 의존하지 않는다 — GUI 없이 시험할 수 있어야 한다.
"""

import time


class CheckResult:
    """점검 한 항목의 결과."""

    def __init__(self, key, name, ok, detail="", retryable=False):
        self.key = key
        self.name = name
        self.ok = ok
        self.detail = detail
        self.retryable = retryable      # 수동 점검에서 「재연결」 버튼을 붙일지

    @property
    def mark(self):
        return "✓" if self.ok else "✗"

    def __repr__(self):
        return f"<{self.key} {'OK' if self.ok else 'FAIL'} {self.detail}>"


# 화면에 쓰는 이름. 🔴 "1차"·"2차"라는 말을 쓰지 않는다 — 차수는 내부 구분이다.
STAGE1_ITEMS = ("camera", "detector", "hand", "interlock", "gpio")
STAGE2_ITEMS = ("stream", "buttons", "hand_infer", "interlock_ack")


def run_stage1(ctx):
    """기동 점검 — 부품이 다 있나. ctx = 점검 대상 묶음(아래 키를 갖는 객체/딕셔너리)."""
    g = ctx.get if isinstance(ctx, dict) else lambda k, d=None: getattr(ctx, k, d)
    out = []

    cam = g("camera_thread")
    connected = bool(cam and getattr(cam, "sock", None) is not None)
    gave_up = bool(cam and getattr(cam, "gave_up", False))
    out.append(CheckResult(
        "camera", "카메라 연결", connected,
        "연결됨" if connected else ("자동 재시도 중단됨" if gave_up else "연결 시도 중"),
        retryable=True))

    det = g("detector_available", None)
    out.append(CheckResult("detector", "검출 모델", bool(det),
                           "console_v2 로드됨" if det else "로드 실패", retryable=True))

    hand = g("hand_tracker")
    hand_ok = bool(hand and getattr(hand, "available", False))
    out.append(CheckResult("hand", "손 검출 모델", hand_ok,
                           "사용 가능" if hand_ok
                           else f"비활성 — {getattr(hand, 'reason', '사유 없음')}",
                           retryable=False))

    itl = g("interlock")
    itl_ok = bool(itl and getattr(itl, "connected", False))
    out.append(CheckResult("interlock", "인터락 연결", itl_ok,
                           "연결됨" if itl_ok else "미연결(fallback)", retryable=True))

    gpio = g("gpio_input")
    gpio_ok = bool(gpio and getattr(gpio, "available", True))
    out.append(CheckResult("gpio", "GPIO 입력", gpio_ok,
                           "준비됨" if gpio_ok else "미연결 — 키보드로 대체", retryable=True))
    return out


def run_stage2(ctx, now=None):
    """작업 시작 점검 — 지금 실제로 되나.

    🔴 핵심은 **버튼 검출**이다. 카메라가 연결돼 있어도 콘솔이 화면 밖이면
       아무것도 감지하지 못하는데, 지금은 그것을 작업 시작 전에 확인할 방법이 없다.
       이 점검은 "장비가 켜졌나"가 아니라 **"지금 이 자세로 감지가 되나"** 를 묻는다.
    """
    g = ctx.get if isinstance(ctx, dict) else lambda k, d=None: getattr(ctx, k, d)
    now = time.time() if now is None else now
    out = []

    last = g("last_frame_time", 0.0) or 0.0
    fresh = (now - last) < 2.0
    out.append(CheckResult("stream", "영상 수신", fresh,
                           f"{now - last:.1f}초 전 프레임" if last else "프레임 없음",
                           retryable=True))

    # 🔴 EMO 는 세지 않는다 — 실콘솔에서 카메라 화각 밖이라 비전에 안 잡힌다.
    #    안전에는 영향 없다: EMO 는 GPIO 물리 입력으로 들어온다.
    seen = set(g("seen_buttons", ()) or ())
    want = {"B1", "B2", "B3", "B4"}
    found = want & seen
    out.append(CheckResult("buttons", "버튼 검출", found == want,
                           f"{len(found)}/4 검출 ({', '.join(sorted(found)) or '없음'})",
                           retryable=False))

    # 손 검출은 **추론이 돌기만 하면 통과**(느슨) — design §4.2.
    # detect() 가 모델없음·손없음·실패를 전부 None 으로 돌려줘 밖에서 구분이 안 되므로,
    # 예외 없이 끝나는지까지가 손 없이 확인할 수 있는 최선이다.
    hand = g("hand_tracker")
    infer_ok, detail = _probe_hand(hand, g("last_frame"))
    out.append(CheckResult("hand_infer", "손 검출 동작", infer_ok, detail, retryable=False))

    itl = g("interlock")
    ack = bool(itl and getattr(itl, "connected", False))
    out.append(CheckResult("interlock_ack", "인터락 응답", ack,
                           "ACK 확인" if ack else "응답 없음(fallback)", retryable=True))
    return out


def _probe_hand(hand, frame):
    """프레임 하나로 손 검출 추론을 돌려 본다. 결과가 '손 없음'이어도 통과다."""
    if hand is None or not getattr(hand, "available", False):
        return False, "모델 비활성"
    if frame is None:
        return False, "확인할 프레임 없음"
    try:
        t0 = time.perf_counter()
        hand.detect(frame)
        ms = (time.perf_counter() - t0) * 1000
        return True, f"추론 {ms:.0f}ms"
    except Exception as e:
        return False, f"추론 실패: {type(e).__name__}"


def summary(results):
    """결과 묶음 → (전부 통과?, '3/5' 문자열)."""
    ok = sum(1 for r in results if r.ok)
    return ok == len(results), f"{ok}/{len(results)}"
