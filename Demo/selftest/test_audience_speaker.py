"""관객 소리(TV) 거울 검증 — 소리 재료(프레임 풀기 · 크기 맞춤 · 레이트 · 띠링)와 통로(AudienceSpeaker).

실행: python3 Demo/selftest/test_audience_speaker.py
정본 = 상위 docs/superpowers/specs/2026-10-21-관객소리TV-design.md 4장
"""
import os
import re
import sys
import wave

import numpy as np

_DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DEMO)
sys.path.insert(0, os.path.join(_DEMO, "voice"))

import audience_speaker as aus   # noqa: E402
import config                    # noqa: E402
import voice_assistant as va     # noqa: E402
import voice_tts                 # noqa: E402

FW = os.path.join(_DEMO, "..", "arduino", "glass_voice", "glass_voice.ino")
WAV = os.path.join(_DEMO, "voice", "wav", "cue_g1_0a.wav")
_fails = []


def check(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        _fails.append(msg)


def _peak_hz(seg, rate):
    seg = np.asarray(seg, dtype=np.float64)
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    return float(np.fft.rfftfreq(len(seg), 1 / rate)[int(np.argmax(spec))])


def test_parse_frame_roundtrip():
    print("\n[재료] 프레임 풀기 — 합성 답 · 고정 wav")
    pcm = (np.sin(np.arange(1600) / 5) * 3000).astype("<i2")
    got = aus.parse_frame(voice_tts.frame(pcm.tobytes(), 16000))
    check(got is not None and got[1] == 16000 and np.array_equal(got[0], pcm), "합성 답 프레임 = 원래 샘플 · 16000Hz")
    body, _ = va.wav_payload(WAV)
    with wave.open(WAV) as w:
        rate, raw = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), "<i2")
    got = aus.parse_frame(body)
    check(got is not None and got[1] == rate and np.array_equal(got[0], raw), f"고정 wav 프레임 = 원래 샘플 · {rate}Hz")


def test_parse_frame_rejects_bad():
    print("\n[재료] 잘못된 프레임은 None")
    body = voice_tts.frame((np.ones(100) * 5).astype("<i2").tobytes(), 16000)
    bad_chk = body[:-6] + bytes([body[-6] ^ 1]) + body[-5:]
    check(aus.parse_frame(bad_chk) is None, "체크섬이 다르면 None")
    check(aus.parse_frame(body[:-2]) is None, "꼬리(P) 없으면 None")
    check(aus.parse_frame(b"") is None, "빈 바이트는 None")
    check(aus.parse_frame(b"B\n") is None, "한 글자 명령은 None")


def test_normalize_peak():
    print("\n[재료] 크기 맞춤")
    a = np.array([0, 1000, -3394, 200], dtype=np.int16)
    out = aus.normalize(a, 29162)
    check(int(np.abs(out).max()) == 29162 and out.dtype == np.int16, f"최고 3394 → 29162 ({int(np.abs(out).max())})")
    z = aus.normalize(np.zeros(10, np.int16), 29162)
    check(int(np.abs(z).max()) == 0, "무음은 그대로 0")


def test_resample_length():
    print("\n[재료] 레이트 바꾸기")
    a = (np.sin(np.arange(24000) / 7) * 1000).astype(np.int16)
    out = aus.resample(a, 24000, 48000)
    check(abs(len(out) - 48000) <= 1 and out.dtype == np.int16, f"24000 → 48000 길이 2배 ({len(out)})")
    check(len(aus.resample(a, 48000, 48000)) == len(a), "같은 레이트면 길이 그대로")


def test_chime_shape():
    print("\n[재료] 띠링 · 닫힘음 — 펌웨어와 같은 모양(make_guide.chime 재사용)")
    rate, peak = 48000, 29162
    for kind, first, second in (("open", 1568, 2093), ("close", 2093, 1568)):
        c = aus.chime_pcm(kind, rate, peak)
        check(abs(len(c) - int(0.43 * rate)) <= 2, f"{kind} 길이 0.43초({len(c) / rate:.3f})")
        check(0 < int(np.abs(c).max()) <= peak, f"{kind} 최고 진폭 ≤ {peak}")
        f1 = _peak_hz(c[int(0.040 * rate):int(0.140 * rate)], rate)
        f2 = _peak_hz(c[int(0.200 * rate):int(0.380 * rate)], rate)
        check(abs(f1 - first) <= 20 and abs(f2 - second) <= 20, f"{kind} 높이 {first}→{second} ({f1:.0f}→{f2:.0f})")
    check(aus.chime_pcm("없음", rate, peak) is None, "모르는 종류는 None")


def test_close_chime_matches_firmware():
    print("\n[재료] 닫힘음 순서 = 펌웨어 closeChime()")
    src = open(FW, encoding="utf-8").read()
    body = src[src.index("static void closeChime()"):]
    body = body[:body.index("}")]
    tones = re.findall(r"toneSeg\((CHIME_\w+), \1, (\d+)", body)
    check(tones == [("CHIME_HI", "120"), ("CHIME_LO", "180")], f"펌웨어 닫힘음 = HI 120ms → LO 180ms ({tones})")


def test_config_values():
    print("\n[설정] 관객 소리 값")
    check(config.AUDIENCE_PEAK == 29162 and config.AUDIENCE_RATE == 48000, "기준 진폭 29162 · 48000Hz")
    check(config.AUDIENCE_TAIL_MAX_SEC == 0.5 and config.AUDIENCE_TAIL_PAD_SEC == 0.3, "꼬리 상한 0.5 · 여유 0.3(실측 TV 0.22초 + 여유)")
    check(config.AUDIENCE_TV_LAG_SEC == 0.22 and isinstance(config.AUDIENCE_ADVANCE, bool), "TV 지연 0.22 · 앞당기기 켬/끔")
    check(isinstance(config.AUDIENCE_SPEAKER, bool), "켬/끔 = bool")


# ── 통로(AudienceSpeaker) — 가짜 재생기: 표준 입력을 실시간 속도로 읽어 파일에 적는다 ─────────────
import atexit     # noqa: E402
import shutil     # noqa: E402
import tempfile   # noqa: E402
import time       # noqa: E402

_TMPDIR = tempfile.mkdtemp(prefix="sop_audience_test_")
atexit.register(shutil.rmtree, _TMPDIR, True)     # 끝나면 지운다(최종 리뷰 Minor 5 — /tmp 에 .raw 가 쌓였다)


def _tmpraw():
    fd, p = tempfile.mkstemp(suffix=".raw", dir=_TMPDIR)
    os.close(fd)
    return p

_FAKE = ("import sys,time\n"
         "f=open(sys.argv[1],'ab')\n"
         "while True:\n"
         "    b=sys.stdin.buffer.read(2048)\n"
         "    if not b: break\n"
         "    f.write(b); f.flush(); time.sleep(len(b)/2/48000)\n")


def _player(path):
    return [sys.executable, "-c", _FAKE, path]


def _read(path, start=0):
    with open(path, "rb") as f:
        f.seek(start)
        return np.frombuffer(f.read(), dtype="<i2")


def _frame(sec, rate=16000, amp=3000):
    t = np.arange(int(sec * rate))
    return voice_tts.frame((np.sin(t / 3) * amp).astype("<i2").tobytes(), rate)


# 멈춘 뒤에도 이미 넘긴 소리는 나간다 — 상한 = 「실제 시간보다 앞서 넣지 않기」(AHEAD_MAX_SEC) + 가짜 재생기 한 번 읽기 + 한 덩어리
_SLACK = int(aus.AudienceSpeaker.AHEAD_MAX_SEC * 48000 * 2) + 3 * 2048


def _mk(path, on=None, **kw):
    logs = []
    sp = aus.AudienceSpeaker(on or (lambda: True), cmd=_player(path), log=logs.append, flag_ttl=0.05, **kw)
    sp.start()
    return sp, logs


def test_silence_when_idle():
    print("\n[통로] 쉴 때는 무음을 흘린다")
    p = _tmpraw()
    sp, _ = _mk(p)
    time.sleep(0.4)
    a = _read(p)
    sp.close()
    check(a.size > 0 and int(np.abs(a).max()) == 0, f"받은 샘플 {a.size}개 · 전부 0")


def test_begin_plays_prepared():
    print("\n[통로] 준비 → 시작이면 크기 맞춘 소리가 나간다")
    p = _tmpraw()
    sp, _ = _mk(p)
    time.sleep(0.1)
    sp.prepare(_frame(0.3))
    a0 = _read(p)
    check(int(np.abs(a0).max()) == 0, "prepare 만으로는 소리가 안 나간다")
    sp.begin()
    time.sleep(0.6)
    a = _read(p)
    sp.close()
    check(int(np.abs(a).max()) >= 29000, f"최고 진폭 {int(np.abs(a).max())} ≥ 29000")


def test_stop_cuts():
    print("\n[통로] 멈춤이면 바로 무음")
    p = _tmpraw()
    sp, _ = _mk(p)
    sp.prepare(_frame(3.0))
    sp.begin()
    time.sleep(0.3)
    sp.stop()
    at = os.path.getsize(p)
    time.sleep(0.4)
    tail = _read(p, at + _SLACK)        # 이미 넘긴 몫(_SLACK) 넘어서는 무음이어야 한다
    sp.close()
    check(tail.size > 0 and int(np.abs(tail).max()) == 0, f"멈춘 뒤 {tail.size}샘플 전부 0")
    check(not sp.busy, "busy = False")


def test_disable_mid_sound_goes_silent():
    print("\n[통로] 소리 도중 끄면 바로 무음 · 끈 동안 begin 무시")
    p = _tmpraw()
    on = [True]
    sp, _ = _mk(p, on=lambda: on[0])
    sp.prepare(_frame(3.0))
    sp.begin()
    time.sleep(0.3)
    on[0] = False
    time.sleep(0.15)
    at = os.path.getsize(p)
    time.sleep(0.4)
    tail = _read(p, at + _SLACK)
    check(tail.size > 0 and int(np.abs(tail).max()) == 0, "끈 뒤 무음")
    sp.prepare(_frame(0.5))
    sp.begin()
    sp.chime("open")
    time.sleep(0.3)
    check(not sp.busy, "끈 동안 begin · chime 은 무시")
    sp.close()


def test_player_missing_is_silent():
    print("\n[통로] 재생기가 없어도 예외 없이 조용히 빠진다")
    logs = []
    sp = aus.AudienceSpeaker(lambda: True, cmd=["/없는/재생기"], log=logs.append)
    try:
        sp.start()
        sp.prepare(_frame(0.2))
        sp.begin()
        sp.chime("open")
        sp.stop()
        sp.wait_tail(0.5)
        time.sleep(0.5)
        sp.close()
        ok = True
    except Exception as e:              # noqa: BLE001
        ok = False
        logs.append(f"예외 {e}")
    check(ok, "start · prepare · begin · chime · stop · wait_tail · close 모두 예외 없음")
    check(len(logs) == 1, f"로그 한 줄만({len(logs)}줄: {logs[:3]})")


def test_player_dies_restarts_once():
    print("\n[통로] 재생기가 죽으면 한 번 다시 띄우고 · 연달아 죽으면 쉰다")
    p = _tmpraw()
    sp, logs = _mk(p, retry_sec=10.0)
    time.sleep(0.2)
    first = sp._proc.pid
    sp._proc.kill()
    time.sleep(0.4)
    second = sp._proc.pid if sp._proc is not None else None
    check(second is not None and second != first, f"새 재생기로 다시 흐름({first} → {second})")
    sp.prepare(_frame(0.3))
    sp.begin()
    time.sleep(0.6)
    check(int(np.abs(_read(p)).max()) >= 29000, "다시 띄운 뒤 소리가 나간다")
    sp._proc.kill()
    time.sleep(0.5)
    check(sp._proc is None, "연달아 죽으면 쉰다(재생기 없음)")
    sp.close()


def test_wait_tail_bounded():
    print("\n[통로] 꼬리 기다림 — 상한 · 소리 없으면 즉시")
    p = _tmpraw()
    sp, _ = _mk(p)
    t = time.monotonic()
    sp.wait_tail(0.5)
    check(time.monotonic() - t < 0.05, "소리 없으면 즉시 돌아온다")
    sp.prepare(_frame(5.0))
    sp.begin()
    t = time.monotonic()
    sp.wait_tail(0.5)
    dt = time.monotonic() - t
    sp.close()
    check(0.45 <= dt <= 0.6, f"5초 소리에도 0.5초 상한({dt:.2f}초)")



def test_late_start_backlog_bounded():
    print("\n[통로] 🔴 검토 I1 — 재생기가 늦게 읽기 시작해도 관에 쌓이는 소리는 상한(약 0.1초) 안")
    late = _FAKE.replace("f=open(sys.argv[1],'ab')\n", "f=open(sys.argv[1],'ab')\ntime.sleep(0.3)\n")
    p = _tmpraw()
    sp = aus.AudienceSpeaker(lambda: True, cmd=[sys.executable, "-c", late, p], log=lambda m: None, flag_ttl=0.05)
    sp.start()
    time.sleep(1.0)
    sp.prepare(_frame(1.0))
    t0 = time.monotonic()
    sp.begin()
    lag = None
    while time.monotonic() - t0 < 1.5:
        a = _read(p)
        if a.size and int(np.abs(a).max()) > 0:
            lag = time.monotonic() - t0
            break
        time.sleep(0.005)
    sp.close()
    check(lag is not None and lag <= 0.2, f"시작 지연 0.3초 재생기에서도 소리가 {lag if lag is None else round(lag, 3)}초 뒤에 나감(≤ 0.2)")


def test_prepare_skipped_when_off():
    print("\n[통로] 검토 Minor 1 — 「TV 소리」 끔이면 프레임을 풀지 않는다(안경 쪽 시간 0)")
    sp = aus.AudienceSpeaker(lambda: False, cmd=["/없는/재생기"], log=lambda m: None)
    sp.prepare(_frame(1.0))
    check(sp._prepared is None, "끔 → 준비한 것 없음")


def test_wait_tail_skips_stuck_player():
    print("\n[통로] 검토 Minor 2 — 재생기가 읽지 않고 막혀 있으면 꼬리를 기다리지 않는다")
    stuck = "import time\ntime.sleep(30)\n"
    sp = aus.AudienceSpeaker(lambda: True, cmd=[sys.executable, "-c", stuck], log=lambda m: None, flag_ttl=0.05)
    sp.start()
    time.sleep(1.2)                       # 관이 가득 차 공급 스레드가 쓰기에서 막힘
    sp.prepare(_frame(2.0))
    sp.begin()
    t0 = time.monotonic()
    sp.wait_tail(0.5)
    dt = time.monotonic() - t0
    sp.close()
    check(dt < 0.1, f"막힌 재생기 → 바로 돌아옴({dt:.2f}초)")


def test_next_chunk_reads_flag_outside_lock():
    print("\n[통로] 검토 Minor 3 — 설정(상태 파일)은 잠금 밖에서 읽는다")
    import inspect
    src = inspect.getsource(aus.AudienceSpeaker._next_chunk)
    check(src.index("self.enabled()") < src.index("with self._lock"), "enabled() 가 with self._lock 보다 앞")


# ── TV 앞당겨 틀기(설계 11장) — 안경이 다 받기 전에 TV 를 미리 튼다 ─────────────────────
def _onset(p, t_from, limit=2.0):
    """파일에 소리(0 아닌 샘플)가 처음 나온 때 — t_from 부터 단조 시계로."""
    while time.monotonic() - t_from < limit:
        a = _read(p)
        if a.size and int(np.abs(a).max()) > 0:
            return time.monotonic() - t_from
        time.sleep(0.003)
    return None


def _adv(p, spb, lag=0.22, advance=True):
    sp = aus.AudienceSpeaker(lambda: True, cmd=_player(p), log=lambda m: None, flag_ttl=0.05,
                             advance=advance, tv_lag=lag, spb=spb)
    sp.start()
    time.sleep(0.6)
    return sp


def test_advance_starts_before_play_line():
    print("\n[앞당김] 예상 받기 시간 − TV 지연 뒤에 「[재생]」 없이 먼저 튼다")
    p = _tmpraw()
    f = _frame(1.0)
    sp = _adv(p, spb=0.5 / len(f))          # 받는 데 0.5초로 가정 → 0.28초 뒤 시작
    t0 = time.monotonic()
    sp.prepare(f, t_send=t0)
    on = _onset(p, t0)
    sp.close()
    check(on is not None and 0.2 <= on <= 0.5, f"「[재생]」 없이 약 0.28초(+관 몫) 뒤 나감({on if on is None else round(on, 3)}초)")


def test_advance_short_sound_starts_now():
    print("\n[앞당김] 앞당길 몫이 0 이하(짧은 소리)면 바로 튼다")
    p = _tmpraw()
    f = _frame(0.3)
    sp = _adv(p, spb=0.05 / len(f))         # 받는 데 0.05초 < TV 지연 0.22초
    t0 = time.monotonic()
    sp.prepare(f, t_send=t0)
    on = _onset(p, t0)
    sp.close()
    check(on is not None and on <= 0.25, f"바로 나감({on if on is None else round(on, 3)}초)")


def test_begin_after_advance_does_not_restart():
    print("\n[앞당김] 앞당겨 튼 뒤 「[재생]」(begin)이 와도 처음부터 다시 틀지 않는다")
    p = _tmpraw()
    f = _frame(1.0)
    sp = _adv(p, spb=0.01 / len(f))
    t0 = time.monotonic()
    sp.prepare(f, t_send=t0)
    time.sleep(0.4)
    pos = sp._pos
    sp.begin()
    check(sp.busy and sp._pos >= pos, f"이어서 흐름(위치 {pos} → {sp._pos})")
    sp.close()


def test_begin_before_schedule_starts_now():
    print("\n[앞당김] 「[재생]」이 예정보다 먼저 오면 그때 바로 튼다")
    p = _tmpraw()
    f = _frame(1.0)
    sp = _adv(p, spb=3.0 / len(f))          # 받는 데 3초로 잘못 가정 → 예정 2.78초 뒤
    t0 = time.monotonic()
    sp.prepare(f, t_send=t0)
    time.sleep(0.1)
    sp.begin()
    on = _onset(p, t0)
    sp.close()
    check(on is not None and on <= 0.35, f"begin 때 바로({on if on is None else round(on, 3)}초)")


def test_learns_receive_time():
    print("\n[앞당김] 「[재생]」이 온 때로 받는 시간(초/바이트)을 고쳐 간다")
    p = _tmpraw()
    f = _frame(1.0)
    sp = _adv(p, spb=3.0 / len(f))
    before = sp.spb
    t0 = time.monotonic() - 0.4             # 0.4초 전에 보냈고 지금 「[재생]」
    sp.prepare(f, t_send=t0)
    sp.begin()
    time.sleep(0.15)                        # 풀기는 따로 도는 스레드 — 끝난 뒤에 본다
    sp.close()
    want = 0.4 / len(f)
    check(abs(sp.spb - want) < abs(before - want), f"실제(0.4초) 쪽으로 다가감({before:.2e} → {sp.spb:.2e} · 실제 {want:.2e})")



def test_learns_fixed_plus_per_byte():
    print("\n[앞당김] 받는 시간 = 늘 드는 몫 + 크기 비례 몫 — 두 크기를 배우면 세 번째 크기를 맞힌다(실측 10/21: 약 0.2초 + 1.25e-6초/바이트)")
    sp = aus.AudienceSpeaker(lambda: True, cmd=["/없는/재생기"], log=lambda m: None)
    a, b = 0.205, 1.25e-6
    for n in (86_000, 120_000, 86_000, 120_000, 60_000, 200_000):
        with sp._lock:
            sp._learn(100.0, n, 100.0 + a + b * n)
    for n in (50_000, 400_000):
        est = sp.receive_est(n)
        want = a + b * n
        check(abs(est - want) / want < 0.05, f"{n // 1000}KB 예측 {est:.3f}초 · 실제 {want:.3f}초")


def test_receive_prior_from_measurement():
    print("\n[앞당김] 처음 값 = 10/21 실측(늘 드는 몫 + 비례 몫) — 첫 문장부터 맞게 · spb 를 직접 주면 그 값")
    sp = aus.AudienceSpeaker(lambda: True, cmd=["/없는/재생기"], log=lambda m: None)
    want = config.AUDIENCE_RECV_FIXED_SEC + config.AUDIENCE_RECV_SEC_PER_BYTE * 86_400
    check(abs(sp.receive_est(86_400) - want) < 0.01, f"86KB 처음 예측 {sp.receive_est(86_400):.3f}초 · 실측 직선 {want:.3f}초")
    sp2 = aus.AudienceSpeaker(lambda: True, cmd=["/없는/재생기"], log=lambda m: None, spb=1e-6)
    check(abs(sp2.receive_est(100_000) - 0.1) < 1e-9, "spb 를 주면 처음 값 대신 비례(시험용)")

def test_advance_off_waits_play_line():
    print("\n[앞당김] 끄면(SOP_AUDIENCE_ADVANCE=0) 종전대로 「[재생]」 때")
    p = _tmpraw()
    f = _frame(0.5)
    sp = _adv(p, spb=0.0, advance=False)
    t0 = time.monotonic()
    sp.prepare(f, t_send=t0)
    time.sleep(0.4)
    check(int(np.abs(_read(p)).max()) == 0, "prepare 만으로는 안 나감")
    sp.begin()
    check(_onset(p, time.monotonic()) is not None, "begin 에 나감")
    sp.close()

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:      # noqa: BLE001 — 하나가 터져도 나머지를 본다
                check(False, f"{name} 예외 — {type(e).__name__}: {e}")
    print(f"\n{'❌ 실패 ' + str(len(_fails)) + '건' if _fails else '✅ 모두 통과'}")
    sys.exit(1 if _fails else 0)
