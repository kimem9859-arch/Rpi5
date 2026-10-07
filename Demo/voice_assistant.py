#!/usr/bin/env python3
"""음성비서 데몬 — 「가디언」 → 띠링 → 질문 → 답(LLM 또는 고정 wav).

실행: ./Demo/run_voice.sh [--forever]   (= ~/env/tts/.venv/bin/python Demo/voice_assistant.py)
      시연에서는 run_demo.sh 가 함께 띄운다(설계 2026-10-03 §4.6).
정본: ../docs/superpowers/specs/2026-10-03-음성비서-시연안정화-design.md (안정화)
      · 2026-09-07-음성비서-LLM-design.md (B 갈래) · 2026-09-06-음성비서-시연구현-design.md (A 갈래)

🔑 GUI 를 0줄도 건드리지 않는다 — 별도 프로세스이고, 공구·상태는 GUI 가 /dev/shm 에 쓴 파일을 읽기만 한다.
🔴 접속 주소는 Demo/.camera_ip 를 붙을 때마다 다시 읽는다 — mDNS 를 쓰지 않기로 했고
   (통신경로 설계 §6-②), 그 덕에 iptime·폰·파이AP 어느 폴백에서도 그대로 돈다.
🔑 구조 — 수신 스레드(voice_mic)가 업링크를 늘 비우고, 메인 루프가 VAD·STT 를 돌려 발화를
   Assistant 에 넘긴다. 오프라인 리허설 = Demo/test/fake_glass.py · 증상별 대응 = Demo/voice/시연절차.md.
"""
import argparse
import array
import atexit
import json
import os
import socket
import struct
import shutil
import sys
import threading
import time
import wave

import numpy as np

_DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DEMO_DIR)

from voice_lib import (answer_key, find_utterance, is_question,
                       is_tool_question, is_wake, noise_floor, read_tool_dets)
from voice_lib import rms as vl_rms
from voice_mic import MicReceiver

import config
import voice_card
import voice_llm
import voice_tts
import measure_log

# 🔑 보드는 하나다(9/7 한 보드 복귀 · 설계 2026-10-03 §4.9) — 주소 = Demo/.camera_ip.
IP_FILE  = os.path.join(_DEMO_DIR, ".camera_ip")
WAV_DIR  = os.path.join(_DEMO_DIR, "voice", "wav")
MIC_PORT = 8889
CMD_PORT = 8890
RATE     = 16000

STT_DIR   = os.path.expanduser("~/env/tts/sherpa-onnx-zipformer-korean-2024-06-24")
HOTWORDS  = os.path.expanduser("~/lab/tts/hotwords_ko.txt")
BPE_VOCAB = os.path.expanduser("~/lab/tts/bpe.vocab")

WINDOW_SEC = 6.0      # 판정에 쓰는 최근 구간
LISTEN_SEC = 20.0     # 🔑 호출 뒤 질문을 기다리는 시간.
                      #    🔴 8초는 짧았다 — 2026-09-07 실측에서 사용자가 다시
                      #    말하기까지 12초가 걸려 깨어남이 이미 풀려 있었다.
LAG_LIMIT  = 2.0      # 🔴 도착한 지 이보다 오래된 소리는 밀린 것 — 버린다(최신 우선 · voice_mic)
QUIET_TAIL = 0.4      # 발화가 끝났다고 보기까지 필요한 뒤쪽 무음
VOLUME     = 5        # 🔑 펌웨어 음량 1~5. 기본 3 은 실청취에서 작았다(2026-09-07)
VAD_HOP_SEC = 0.25    # 🔑 새 소리가 이만큼 쌓였을 때만 판정한다 — 512샘플 조각마다 버퍼 전체를 다시 보던
                      #    것이 무음 대기 CPU 의 원인이었다(설계 2026-10-03 §4.1 · Q7 · 10/03 실측)
STALL_SEC  = 3.0      # 🔴 펌웨어는 접속 중 쉬지 않고 보낸다 — 이만큼 0바이트면 반열림으로 보고 다시 붙는다(P5)
RETRY_SEC  = 3.0      # 다시 붙기 전 대기
ALERT_POLL_SEC = 0.1    # 🔑 상태 감시 간격 — 알림 목표 0.3초(설계 2026-10-04 §4.3)의 한 몫

# 🔑 한 대만 돈다 — 명령 채널(8890)은 손님 하나라 둘이 돌면 서로 끊는다(R2 통신 규약 대조표).
LOCK_FILE = os.environ.get("SOP_VOICE_LOCK", "/tmp/sop_voice_assistant.lock")
EXIT_ALREADY_RUNNING = 3      # run_voice.sh --forever 가 이 코드면 감시를 멈춘다
MAIN_ERR_LIMIT = 5            # 발화마다 오류가 이만큼 이어지면 데몬을 끝낸다 — 감시가 모델을 새로 올린다(1단계 M3)
_AUTO = object()

# 🔑 보고서 시각자료용 계측 — 발화마다 한 줄씩 JSONL 로 남긴다.
#    환경변수 SOP_VOICE_METRICS 로 경로를 준다(없으면 안 남긴다).
METRICS_PATH = os.environ.get("SOP_VOICE_METRICS")

# 🔑 보고서용 오디오 기록 — 환경변수 SOP_VOICE_AUDIO 로 폴더를 준다(없으면 안 남긴다).
#    귀에 들린 것과 기계가 받은 것을 나중에 대조할 수 있어야 한다.
#      마이크_전체.wav      ESP32 가 보낸 업링크 전부(16kHz)
#      발화_NNN.wav / .txt  잘라낸 발화 구간과 그 STT 결과
#      재생_NNN_<키>.wav    스피커로 내보낸 것(사전 합성된 TTS 원본)
AUDIO_DIR = os.environ.get("SOP_VOICE_AUDIO")


VLOG = measure_log.NullLog()       # 음성 측정 기록(측정 도구 정합 ⑤) — run() 이 SOP_MEASURE_DIR 를 보고 연다


def vev_play_line(t):
    """펌웨어 재생 줄 → 재생 시작·끝 사건(Speaker._drain 이 부른다)."""
    if t.startswith("[재생]"):
        VLOG.event("play_start")
    elif "재생 완료" in t or "재생 중단" in t:
        VLOG.event("play_end", what="완료" if "재생 완료" in t else "중단")


def vev_uplink(total, connected):
    VLOG.event("uplink", bytes=int(total), connected=bool(connected))


def exit_on_sigterm():
    """SIGTERM 을 정상 종료로 — 세션 끝에 감시 스크립트(run_voice.sh 의 trap)가 보내는 SIGTERM 에도 run() 의
    finally 가 돌아 측정 기록을 닫는다(measure_end · 꼬리 사건 — 리뷰 I-1). 측정 중일 때만 main() 이 부른다
    — 끈 시연의 종료 동작은 그대로."""
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def ms_clock(t=None):
    """「HH:MM:SS.mmm」 — 로그 시각을 ms 로(측정 도구 정합 D15)."""
    t = time.time() if t is None else t
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"


def log(msg):
    print(f"[{ms_clock()}] {msg}", flush=True)


def metric(rec):
    """계측 한 줄 — 보고서 그림의 원자료가 된다.

    🔴 판단이 아니라 **관측**만 적는다. 무엇을 들었고 얼마나 걸렸는지.
       해석(인식률·지연 분포)은 나중에 이 파일에서 뽑는다.
    """
    if not METRICS_PATH:
        return
    try:
        with open(METRICS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


class AudioLog:
    """오디오와 변환 결과를 파일로 남긴다 — 없으면 아무것도 안 한다."""

    def __init__(self, path):
        self.dir = path
        self.full = None
        self.n_utt = 0
        self.n_play = 0
        if not path:
            return
        os.makedirs(path, exist_ok=True)
        self.full = wave.open(os.path.join(path, "마이크_전체.wav"), "w")
        self.full.setnchannels(1)
        self.full.setsampwidth(2)
        self.full.setframerate(RATE)

    def mic(self, samples):
        """업링크 원본 — 🔑 수신 스레드에서 불린다(대답하는 동안의 소리도 빠짐없이 남는다)."""
        if self.full:
            self.full.writeframes(samples.tobytes())

    def utterance(self, samples, text):
        """잘라낸 발화 + STT 결과. 🔑 둘을 짝지어 둬야 나중에 대조가 된다."""
        if not self.dir:
            return
        self.n_utt += 1
        base = os.path.join(self.dir, f"발화_{self.n_utt:03d}")
        with wave.open(base + ".wav", "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(array.array("h", samples).tobytes())
        with open(base + ".txt", "w", encoding="utf-8") as f:
            f.write(text + "\n")

    def played(self, key, src):
        if not self.dir:
            return
        self.n_play += 1
        try:
            shutil.copyfile(src, os.path.join(
                self.dir, f"재생_{self.n_play:03d}_{key}.wav"))
        except OSError:
            pass

    def played_pcm(self, key, pcm, rate, text=None):
        """런타임 합성으로 내보낸 소리 — 원본 wav 파일이 없다.

        🔑 문장도 함께 남긴다. 보고서에서 「무슨 말을 했나」가 소리보다 중요하고,
           소리는 문장 + 모델로 언제든 다시 만들 수 있다.
        """
        if not self.dir:
            return
        self.n_play += 1
        base = os.path.join(self.dir, f"재생_{self.n_play:03d}_{key}")
        try:
            with wave.open(base + ".wav", "w") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(pcm)
            if text:
                with open(base + ".txt", "w", encoding="utf-8") as f:
                    f.write(text + "\n")
        except OSError:
            pass

    def close(self):
        if self.full:
            self.full.close()
            self.full = None


def open_audio_log(path):
    """오디오 기록을 열고 **프로그램이 끝날 때 닫도록** 등록한다(V4 — 파일 핸들 정리).

    🔑 닫지 않아도 파일은 깨지지 않는다 — 파이썬 `wave` 는 쓸 때마다 머리(길이)를 고쳐 써서,
       SIGTERM 으로 끝나도 마이크_전체.wav 는 온전하다(③ 리뷰 M-3 · 2026-09-26 Python 3.13 확인).
    ⚠️ atexit 은 정상 종료·Ctrl+C 에서만 돈다 — `voice/record_voice_demo.py` 는 `terminate()`
       (SIGTERM)로 끝내므로 그 경로에서는 돌지 않는다(위 이유로 파일은 그래도 온전하다).
    """
    alog = AudioLog(path)
    atexit.register(alog.close)
    return alog


def esp_ip():
    """보드 주소 = `Demo/.camera_ip` — 보드가 하나다(설계 2026-10-03 §4.9).

    🔴 mDNS 를 쓰지 않으므로(통신경로 설계 §6-②) 주소는 파일이 정본이고,
       매번 다시 읽어 통신경로 폴백(iptime→폰→파이AP)을 따라간다.
    """
    try:
        ip = open(IP_FILE, encoding="utf-8").read().strip()
    except OSError:
        ip = ""
    if not ip:
        raise SystemExit(f"🔴 보드 주소를 못 찾았다 — {IP_FILE} 를 만들어라(arduino/read_esp32_ip.sh)")
    return ip


def build_stt():
    """🔴 스레드 2개 — 4개면 Hailo·MediaPipe 와 CPU 를 다툰다.

    핫워드 가중치 3.0 = §10.52 에서 고른 잠정값(도메인 용어 3/9 → 7/9).
    """
    import sherpa_onnx
    return sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=f"{STT_DIR}/encoder-epoch-99-avg-1.int8.onnx",
        decoder=f"{STT_DIR}/decoder-epoch-99-avg-1.onnx",
        joiner=f"{STT_DIR}/joiner-epoch-99-avg-1.int8.onnx",
        tokens=f"{STT_DIR}/tokens.txt",
        num_threads=2,
        decoding_method="modified_beam_search",
        hotwords_file=HOTWORDS,
        hotwords_score=3.0,
        modeling_unit="bpe",
        bpe_vocab=BPE_VOCAB,
    )


def transcribe(rec, samples):
    st = rec.create_stream()
    st.accept_waveform(RATE, [s / 32768.0 for s in samples])
    rec.decode_stream(st)
    return st.result.text


def wav_payload(path):
    """펌웨어의 `W`+`P` 프레임을 만든다. 체크섬은 펌웨어 checksum() 과 같아야 한다."""
    with wave.open(path) as w:
        rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    a = array.array("h")
    a.frombytes(raw)
    chk = sum(v & 0xFFFF for v in a) & 0xFFFFFFFF
    return (f"W {len(a)} {rate}\n".encode() + a.tobytes()
            + struct.pack("<I", chk) + b"P\n"), len(a) / rate


def wav_shape(body):
    """`wav_payload` 가 만든 프레임의 (샘플 수, 레이트) — 머리줄 「W <n> <rate>」."""
    _, n, rate = body.split(b"\n", 1)[0].split()
    return int(n), int(rate)


def load_tts():
    """런타임 합성기 — 못 올리면 None(고정 wav 로만 답한다)."""
    if not config.LLM_ENABLED:
        return None
    try:
        from voice_tts import Tts
        t = Tts()
        log("런타임 TTS 준비됨")
        return t
    except Exception as e:                     # noqa: BLE001
        log(f"🔴 런타임 TTS 를 못 올렸다 — 고정 wav 로만 답한다: {e}")
        return None


def take_lock(path=None):
    """한 대만 돌게 잠근다. 잡았으면 파일 객체(쥐고 있어야 한다) · 이미 잡혀 있으면 None."""
    import fcntl
    f = open(path or LOCK_FILE, "a")      # 🔑 "w" 로 열면 잡기 전에 비워 잡은 쪽의 PID 줄이 지워진다(1단계 M5)
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.truncate(0)
    f.write(f"{os.getpid()}\n")
    f.flush()
    return f


def ready_line(mic, spk, tts, llm):
    """준비 상태 한 줄 — 시연 절차서가 이 줄을 확인한다(설계 §4.6)."""
    def w(ok):
        return "✓" if ok else "✗"
    if llm is None:
        llm_s = "끔"
    elif llm.ready:
        llm_s = "✓"
    elif llm.warming:
        llm_s = "예열 중"
    else:
        llm_s = "✗(배경에서 다시 데운다)"
    # 🔑 마이크는 「지금 붙어 있음」 — generation>0 은 「한 번이라도 붙었음」이라 끊긴 뒤에도 ✓ 였다(1단계 M11)
    return (f"준비 상태 — 마이크 {w(getattr(mic, 'connected', False))} · 명령 채널 {w(spk.s is not None)} · "
            f"STT ✓ · TTS {w(tts is not None)} · LLM {llm_s}")


DROPPED = ["[버림]"]      # 보내기 직전에 낡은 것으로 판정돼 보내지 않았다(최종 리뷰 I2) — 실패가 아니다


class Speaker:
    """명령 채널(8890) — 한 번 붙여 두고 계속 쓴다.

    🔑 매번 새로 붙지 않는 이유 — 펌웨어가 손님 하나를 붙들고 있어서, 끊었다
       붙이면 그 사이 명령이 샐 수 있다.
    🔑 주소는 붙을 때마다 다시 읽는다 — 마이크와 같은 주소를 따라간다(R2 C2 · 설계 2026-10-03 §4.5).
       `ip` 는 문자열 또는 주소를 돌려주는 함수다.
    """

    def __init__(self, ip, port=CMD_PORT):
        self._ip = ip if callable(ip) else (lambda: ip)
        self.port = port
        self.ip = None                # 마지막으로 붙은 주소
        self.s = None
        self.f = None                 # 쓰지 않는다(V1) — 옛 시험·호출부 호환용으로만 남긴다
        self._rbuf = b""              # 소켓에서 받은 아직 줄이 안 된 바이트
        # 🔑 알림 감시와 메인 루프가 함께 쓴다(설계 2026-10-04 §4.3) — `_io` = 보내고 응답을 읽는 한 벌을
        #    한 스레드만 · `_tx` = 바이트를 보내는 동안만(멈춤 `S` 가 소리 파일 본문 사이에 끼지 않게).
        self._io = threading.RLock()
        self._tx = threading.Lock()
        self.last_play_start = None   # 펌웨어 「[재생] …」 을 받은 시각 — 알림 지연을 잰다
        self.last_stopped = False     # 마지막 play 가 「[재생 중단]」으로 끝났나(정상 멈춤 — 실패가 아니다)

    def _ensure(self):
        if self.s is not None:
            self._drop_stale()
        if self.s is None:
            try:
                self.ip = self._ip()
            except (Exception, SystemExit) as e:   # esp_ip() 는 주소 파일이 없으면 SystemExit — 이 전송만 실패로
                raise OSError(str(e)) from None
            self.s = socket.create_connection((self.ip, self.port), 10)
            self.s.settimeout(30)
            self._rbuf = b""
            # 🔑 음량을 붙을 때마다 올린다 — 펌웨어 기본은 3단계(진폭 6000)인데
            #    2026-09-07 실청취에서 **작아서 잘 안 들렸다.** 5단계(13000)로 올리니
            #    "무슨 말인지 들릴 정도"가 됐다(⛔ §10.49 판정 통과).
            #    ⚠️ 배터리 구동에서는 소비가 늘어 슬라이드 스위치 정격(0.3A)에 붙는다
            #       (설계 §5.4) — 시연은 짧아 감수하지만, 상시 운용이면 낮춘다.
            self.s.sendall(f"{VOLUME}\n".encode())
            log(f"명령 채널 연결됨 ({self.ip}:{self.port}) · 음량 {VOLUME}단계")

    def _drop_stale(self):
        """보내기 전에 쌓여 있던 응답을 버린다 — 지난 재생의 늦은 「[재생 완료]」가 이번 확인으로 읽히지 않게.

        🔴 상대가 이미 닫았으면(EOF) 채널을 버린다 — 닫힌 채널에 보낸 띠링은 오류 없이 사라졌다(R3 M1).
        """
        self._rbuf = b""
        self.s.settimeout(0.0)
        try:
            while True:
                try:
                    b = self.s.recv(4096)
                except (BlockingIOError, InterruptedError):
                    return
                if not b:
                    log("⚠️ 명령 채널이 상대 쪽에서 닫혀 있었다 — 다시 붙는다")
                    self.reset()
                    return
        except OSError as e:
            log(f"⚠️ 명령 채널 오류({e}) — 다시 붙는다")
            self.reset()
        finally:
            if self.s is not None:
                self.s.settimeout(30)

    def _drain(self, wait=15.0):
        """펌웨어 응답을 읽어 돌려준다 — 🔑 **보냈다 ≠ 들렸다**.

        🔴 2026-09-07 에 물렸다 — 데몬은 보내기만 하고 응답을 안 봐서, 로그에는
           「재생 → wrench」가 찍혔는데 소리는 안 났다. 펌웨어는 「[적재] … ok」·
           「[재생 완료]」를 돌려주므로 그것을 확인해 기록한다.
        🔑 이번 요청의 확인만 받는다(설계 2026-10-03 §4.5) — 「[적재] … ok」 **뒤의** 「[재생 완료]」만
           완료다. 그 앞에 온 것은 지난 재생의 늦은 응답이라 버린다(R3 I1: 엉뚱한 확인을 성공으로 적었다).
        🔴 끝 응답 없이 끝나면(시간 초과·EOF·FAIL) 명령 채널을 버린다 — 다음 전송이 새로 붙는다(③ 리뷰 M-2).
        🔑 「[재생 중단]」(2026-10-04 · 멈춤 S)도 끝 응답이다 — 채널을 버리지 않는다.
           FAIL 뒤에도 버리는 이유 = 펌웨어가 거절한 본문이 남아 한 글자 명령으로 읽힌다(P4).
        """
        out, loaded, why = [], False, "시간 초과"
        end = time.time() + wait
        self.s.settimeout(1.0)
        while time.time() < end:
            try:
                line = self._readline()
            except (OSError, AttributeError) as e:
                why = f"오류 {e}"
                break
            if line is None:
                # 🔴 재생 중에는 펌웨어가 몇 초간 아무것도 안 보낸다 — 여기서
                #    포기하면 「확인되지 않았다」로 잘못 판정한다(2026-09-07).
                continue
            if not line:
                why = "EOF"
                break
            t = line.decode("utf-8", "replace").strip()
            if not t:
                continue
            if ("재생 완료" in t or "재생 중단" in t) and not loaded:
                continue                       # 지난 재생의 늦은 확인 — 이번 것이 아니다
            out.append(t)
            if "FAIL" in t:
                why = "FAIL"
                break
            if t.startswith("[적재]") and t.endswith("ok"):
                loaded = True
            elif t.startswith("[재생]"):
                vev_play_line(t)
                self.last_play_start = time.time()      # 🔑 소리가 나기 시작한 때(설계 2026-10-04 §4.3 목표 측정)
            elif "재생 완료" in t or "재생 중단" in t:
                vev_play_line(t)
                self.s.settimeout(30)
                return out
        if why == "FAIL":
            log("🔴 펌웨어가 거절했다 — 남은 바이트가 명령으로 읽히지 않게 명령 채널을 다시 붙인다")
        elif why == "EOF":
            log("🔴 재생 확인 중에 명령 채널이 닫혔다 — 다시 붙는다")
        elif why == "시간 초과":
            log(f"⚠️ 재생 확인이 {wait:.0f}초 안에 끝나지 않았다 — 명령 채널을 다시 붙인다")
        else:
            log(f"🔴 재생 확인 중 {why} — 명령 채널을 다시 붙인다")
        self.reset()
        return out

    def _readline(self):
        """한 줄(b"...\\n")을 소켓에서 직접 읽는다. 타임아웃이면 None · 닫혔으면 b"".

        🔴 `socket.makefile()` 을 쓰지 않는다 — 그 객체는 타임아웃이 **한 번** 나면 이후 모든
           읽기가 OSError("cannot read from timed out object") 라, 첫 재생의 무음 뒤로 재생
           확인이 전부 실패했다(검토 C6 · 성능검증 §10.61 「원인 미규명」의 원인). 그 사이
           메인 루프가 재생 중에 마이크를 다시 들었다.
        """
        while b"\n" not in self._rbuf:
            try:
                chunk = self.s.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                line, self._rbuf = self._rbuf, b""
                return line
            self._rbuf += chunk
        line, _, self._rbuf = self._rbuf.partition(b"\n")
        return line + b"\n"

    def send(self, payload, expect=False, still_valid=None):
        """보낸다 — `still_valid` 가 거짓이면 보내지 않고 `DROPPED`.

        🔑 그 확인은 보내기 잠금(`_tx`) 안에서 한다 — 알림 감시는 gen 을 올린 **뒤** 멈춤 S 를 보내므로(같은 잠금),
           확인과 전송 사이에 알림이 끼어 낡은 답이 알림 뒤에 이어 나가는 창이 없다(최종 리뷰 I2).
        """
        with self._io:
            for attempt in (1, 2):
                try:
                    self._ensure()
                    with self._tx:
                        if still_valid is not None and not still_valid():
                            return DROPPED
                        self.s.sendall(payload)
                    if expect:
                        return self._drain()
                    return True
                except OSError as e:
                    log(f"🔴 명령 전송 실패({attempt}): {e}")
                    self.reset()
            return False

    def stop(self):
        """재생 중인 소리를 멈추라고 보낸다(설계 2026-10-04 §4.3) — 응답은 재생하던 쪽(_drain)이 읽는다.

        🔴 `_tx` 만 잡는다 — 재생 확인을 기다리는 동안(_drain)은 그 잠금이 비어 있어 바로 나간다.
        🔑 2단계 펌웨어 전에는 재생이 끝난 뒤 한 글자 명령으로 읽혀 무시된다(해가 없다).
        """
        with self._tx:
            s = self.s
            if s is None:
                return False
            try:
                s.sendall(b"S")
                VLOG.event("stop_sent")
                return True
            except OSError:
                return False

    def reset(self):
        """링크가 끊겼을 때 명령 채널도 버린다 — 다음 send 에서 다시 붙는다."""
        self._rbuf = b""
        if self.s is not None:
            try:
                self.s.close()
            except OSError:
                pass
            self.s = None

    def chime(self):
        return self.send(b"B\n")

    def play(self, key, alog=None, still_valid=None):
        """고정 wav 를 낸다 → 끝까지 나갔거나 도중에 멈췄으면 True(멈춤은 `last_stopped`) · 못 냈으면 False."""
        self.last_stopped = False
        path = os.path.join(WAV_DIR, f"{key}.wav")
        try:
            body, sec = wav_payload(path)
        except Exception as e:                               # noqa: BLE001
            # 🔑 읽는 단계의 모든 실패를 잡는다 — 16비트가 아닌 wav(홀수 길이 ValueError)·rate 0
            #    (ZeroDivisionError)도 데몬을 죽이지 않는다(④ 사소 4).
            # 🔴 그 재생만 실패로 적는다 — 종전에는 try 밖이라 wav 가 없으면(`*.wav` 는 git 밖 —
            #    새 클론·sop-pi-2) 첫 답변에서 **데몬 전체가 죽었다**(검토 C20).
            log(f"🔴 재생 파일을 못 읽었다 → {key} · {e}")
            return False
        n, rate = wav_shape(body)
        if not voice_tts.fits(n, rate):
            # 🔴 LLM 답과 같은 이중 방어 — 펌웨어가 본문을 안 읽고 거절하면 남은 바이트가 명령으로 실행된다(1단계 M7)
            log(f"🔴 고정 소리가 펌웨어 한도를 넘는다 → {key} ({n}샘플 · {rate}Hz) — 보내지 않는다")
            return False
        if alog:
            alog.played(key, path)
        resp = self.send(body, expect=True, still_valid=still_valid)
        if resp is DROPPED:
            return False
        ok = bool(resp) and any("재생 완료" in r for r in resp)
        self.last_stopped = bool(resp) and any("재생 중단" in r for r in resp)
        if ok:
            log(f"재생 → {key} ({sec:.1f}초) · ESP32 확인됨")
        elif self.last_stopped:
            log(f"재생 → {key} · 도중에 멈춤(알림·해제)")
        else:
            log(f"🔴 재생이 확인되지 않았다 → {key} · 응답={resp}")
        return ok or self.last_stopped


def ask_async(ask_fn, card, question):
    """LLM 을 배경에서 부른다 — 「확인 중」 재생과 겹치게 하려는 것이다.

    🔴 순서대로 하면 재생 2초가 지연에 그대로 더해진다. 명령 채널이 하나뿐이라
       (`Speaker`) 재생 완료를 기다리는 동안 메인 루프가 막히기 때문이다.
       먼저 띄워 두면 그 2초가 LLM 시간에 흡수된다(설계 §7).
    """
    box = {}

    def _work():
        box["r"] = ask_fn(card, question)

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    return th, box


class AlertWatcher:
    """상태 감시 — 비상정지·차단·경고로 바뀌면 고정 알림, 풀리면 재생 멈춤(설계 2026-10-04 §4.3).

    🔑 메인 루프와 따로 돈다 — 메인 루프는 STT·LLM 동안 수 초씩 멈춰 있다.
    🔑 **감시와 재생도 따로 돈다**(`start`) — 재생 확인을 기다리는 3~4초 동안 감시가 멈춰 있으면 해제를 못 보고
       멈춤을 못 보내며, 경고 알림 도중 비상정지 알림이 끼어들지 못했다(최종 리뷰 C1 · 사용자 「해제 버튼을 누르면
       바로 음성비서 안내 출력이 멈추는 것」). 재생은 가장 최근 알림 하나만 기다린다.
    `gen` = 알림이 나간 횟수 — 답을 만들던 쪽(Assistant)이 이것이 바뀌었으면 답을 조용히 버린다.
    `speaking` = 알림 재생 중 — 메인 루프가 그동안 들어온 소리를 버린다(G11 원칙 · alert_hold).
    """

    def __init__(self, spk, read_state=None, alog=None, poll_sec=ALERT_POLL_SEC):
        self.spk = spk
        self._read = read_state or voice_card.read_state
        self.alog = alog
        self.poll_sec = poll_sec
        self.gen = 0
        self.speaking = threading.Event()
        self._prev = None
        self._want = None                        # 재생을 기다리는 알림 (키, 상태) — 가장 최근 것 하나
        self._cv = threading.Condition()
        self._player_on = False                  # start() 뒤에만 재생을 따로 돌린다(시험은 step() 을 바로 부른다)

    def step(self):
        """한 번 본다 — 일어난 사건(없으면 None). 시험이 직접 부른다(재생 스레드가 없으면 그 자리에서 낸다)."""
        cur = self._read()
        ev = voice_card.alert_event(self._prev, cur)
        self._prev = cur
        if ev is None:
            return None
        if ev[0] == "알림":
            VLOG.event("alert", key=ev[1],
                       t_pub_ms=measure_log.now_ms(cur["쓴시각_mono"]) if cur and cur.get("쓴시각_mono") else None,
                       state=(cur or {}).get("상태"))
            self.speaking.set()                  # 🔑 gen 보다 먼저 — 메인 루프가 재생 내내 버리게
            self.gen += 1                        # 🔑 멈춤보다 먼저 — 만들던 답이 보내기 잠금 안에서 이것을 본다(I2)
            self.spk.stop()                      # 재생 중이면 멈춘다(2단계 펌웨어 전에는 무시된다)
            if self._player_on:
                with self._cv:
                    self._want = (ev[1], cur)
                    self._cv.notify()
            else:
                self._play(ev[1], cur)
        else:
            with self._cv:
                self._want = None                # 아직 안 나간 알림도 거둔다
            self.spk.stop()
            log("알림 상황이 풀렸다 — 재생 멈춤을 보냈다")
            VLOG.event("alert_clear")
        return ev

    def _play(self, key, cur):
        try:
            ok = self.spk.play(key, self.alog)
            lag = getattr(self.spk, "last_play_start", None)
            t_pub = (cur or {}).get("쓴시각")
            lag_txt = f" · 상태 공개→소리 시작 {lag - t_pub:.2f}초" if lag and t_pub and lag >= t_pub else ""
            VLOG.event("alert_played", key=key, ok=bool(ok))      # 🔑 데몬 로그 줄과 같은 자리(관문 ③)
            log(f"🔔 알림 → {key} · {'재생됨' if ok else '재생 확인 안 됨'}{lag_txt}")
        finally:
            with self._cv:
                if self._want is None:           # 뒤이은 알림이 없을 때만 「알림 중」을 푼다
                    self.speaking.clear()

    def _player(self, stop):
        while not stop.is_set():
            with self._cv:
                if self._want is None:
                    self._cv.wait(0.2)
                    continue
                key, cur = self._want
                self._want = None
            try:
                self._play(key, cur)
            except Exception as e:              # noqa: BLE001 — 재생이 죽으면 알림이 영영 없다
                log(f"🔴 알림 재생 오류 — 계속한다: {type(e).__name__}: {e}")

    def run(self, stop):
        while not stop.is_set():
            try:
                self.step()
            except Exception as e:              # noqa: BLE001 — 감시가 죽으면 알림이 영영 없다
                log(f"🔴 상태 감시 오류 — 계속한다: {type(e).__name__}: {e}")
            stop.wait(self.poll_sec)

    def start(self, stop):
        self._player_on = True
        threading.Thread(target=self._player, args=(stop,), daemon=True).start()
        th = threading.Thread(target=self.run, args=(stop,), daemon=True)
        th.start()
        return th


def alert_hold(alerts, seen):
    """메인 루프가 지금 소리를 버려야 하나 → `(버림, 새 seen)` — 알림 동안 · 끝난 직후 한 번(Review Focus 1)."""
    if alerts is None:
        return False, seen
    if alerts.speaking.is_set():
        return True, seen
    if alerts.gen != seen:
        return True, alerts.gen
    return False, seen


class Assistant:
    """발화 하나를 받아 답한다 — 스피커·합성·LLM·사실 출처는 밖에서 넣는다(selftest 가 가짜를 넣는다).

    정본: ../docs/superpowers/specs/2026-10-03-음성비서-시연안정화-design.md §4.2~§4.5
    갈래:
      작업 전 → notready (카드가 비어 LLM 이 할 말이 없다 · 유형 ⑤)
      LLM 을 안 씀(SOP_LLM=0 · TTS 없음) → A 갈래(어떤 질문이든 공구 키 · 종전 결정)
      LLM 을 쓸 수 없음(예열 전·건너뜀) → 「확인 중」 없이 바로 A 갈래(공구 질문이면 공구 답 · 아니면 unavailable)
      LLM → finalize(한 문장 60자 · 안전 규칙 → 대체 문장) → 합성 → 펌웨어 한도 → 검산 → 전송
      비상 상황(해제 전까지) → 반응 없음(2026-10-04 §4.7)
      장비 센서 질문 → LLM 없이 「확인할 수 없음」(2026-10-04 §4.5)
      LLM 이 못 냄(준비 전·실패·빈답) → 「지금 할 일」 문장 합성 → 실패하면 A(2026-10-04 §4.6)
    🔴 어디서 실패해도 A 갈래로 떨어진다 — 「확인해 보겠습니다」 뒤 침묵을 남기지 않는다(R2 I2).
    """

    def __init__(self, spk, tts=None, llm=None, alog=None, read_state=None, read_tools=None,
                 clock=time.time, alert_gen=None):
        self.spk = spk
        self.tts = tts
        self.llm = llm
        self.alog = alog or AudioLog(None)
        self._read_state = read_state or voice_card.read_state
        self._read_tools = read_tools or read_tool_dets
        self._clock = clock
        self.awake_until = 0.0
        self._alert_gen = alert_gen or (lambda: 0)   # 알림이 나간 횟수(AlertWatcher.gen) — 낡은 답을 버리는 기준
        self._gen0 = 0

    def alert_gen(self):
        return self._alert_gen()

    def on_text(self, text, m, gen0=None):
        """STT 결과 하나. 질문에 답했으면 True — 호출부가 그동안 들어온 소리를 버린다(G11).

        `gen0` = 발화가 끝난 때(받아쓰기 전)의 알림 횟수 — 받아쓰는 사이 알림이 나갔으면 그 질문의 답은 낡았다
        (최종 리뷰 minor). 없으면 지금 값.
        """
        self._gen0 = self._alert_gen() if gen0 is None else gen0
        # 🔑 비상 상황(비상정지·차단·경고 — 해제 버튼을 누르기 전까지)에는 「가디언」에도 질문에도 반응하지
        #    않는다(사용자 2026-10-04 · 설계 §4.7). 알림이 이미 할 일을 말했다. 되돌리기 = 여기서 알림 문장을 한 번 더.
        if voice_card.in_emergency(self._read_state()):
            VLOG.event("emergency_ignored", text=text, wake=is_wake(text))
            m["비상중"] = True
            self.awake_until = 0.0
            if is_wake(text):
                log(f"비상 상황 — 해제 전까지 질문을 받지 않는다: {text}")
            return False
        now = self._clock()
        awake = now < self.awake_until
        wake = is_wake(text)
        m["호출어"] = wake
        if wake:
            VLOG.event("wake")
            t_c = time.time()
            self.spk.chime()
            m["띠링_ms"] = round((time.time() - t_c) * 1000)
            self.awake_until = now + LISTEN_SEC
            awake = True
            log("호출어 인식 → 띠링")
            # 🔑 한 문장에 질문까지 있으면 바로 답한다 — "가디언, 앞에 보이는 게 뭐야?"
        tool_q = is_tool_question(text)          # 🔑 폴백 선택에 쓴다
        m["공구질문"] = tool_q
        # 🔴 질문 판정은 **문맥**이다 — 깨어난 20초 창 안의 발화는 호출어 단독만 빼고 질문으로 본다
        #    (2026-09-08 최종 리뷰 · 목록으로 쫓으면 질문 5종 중 4종이 침묵으로 빠졌다).
        if not (awake and is_question(text, awake)):
            return False
        self._answer(text, tool_q, m)
        self.awake_until = 0.0
        return True

    def _answer(self, text, tool_q, m):
        """🔴 무엇이 나도 침묵하지 않는다 — 예외면 고정 답(최종 리뷰 M2 · 예: 상태 파일의 값이 깨짐)."""
        try:
            self._answer_inner(text, tool_q, m)
        except Exception as e:                 # noqa: BLE001
            log(f"🔴 답을 만들다 예외 — 고정 답으로: {type(e).__name__}: {e}")
            m["답변오류"] = f"{type(e).__name__}: {e}"[:120]
            self._answer_a(tool_q, "고정-오류", m)

    def _stale(self):
        """질문을 받은 뒤 알림이 나갔거나 비상 상황이 됐나 — 그러면 만들던 답은 낡았다.

        🔑 비상 상황도 본다 — 감시가 아직 못 본 0.1초 사이나 알림을 끈 채(SOP_VOICE_ALERTS=0)면 gen 이 그대로라
           「상태가 바뀌었습니다」가 나갔다(최종 리뷰 I2 · 설계 §4.7 비상 상황엔 무반응).
        """
        return self._alert_gen() != self._gen0 or voice_card.in_emergency(self._read_state())

    def _preempted(self, m):
        """낡은 답은 조용히 버린다(설계 2026-10-04 §4.3)."""
        if not self._stale():
            return False
        m["답변출처"] = "알림으로버림"
        log("알림이 먼저 나갔다 — 만들던 답을 버린다")
        return True

    def _answer_inner(self, text, tool_q, m):
        dets, fresh = self._read_tools()
        state = self._read_state()
        facts = voice_card.card_facts(state, dets, fresh)
        m.update({"공구수": len(dets), "공구신선": fresh,
                  "검출": [[str(d[0]), round(float(d[1]), 2)] for d in dets],
                  "단계": facts["단계"], "세션": facts["세션"]})
        if not facts["세션"]:
            self._play_key("notready", "고정-작업전", m)
            return
        llm_on = config.LLM_ENABLED and self.tts is not None and self.llm is not None
        m["LLM사용"] = llm_on
        if not llm_on:
            self._answer_a(tool_q, "고정-LLM미사용", m, any_question=True)
            return
        gated = voice_card.gate_answer(text, facts)
        if gated:
            # 🔑 허가를 묻는 질문 — LLM 을 안 부르고 사실 문장(최종 리뷰 C2 · 사용자 「위험 질문엔 고정 대체 문장」)
            m["위험질문"] = True
            log(f"허가를 묻는 질문 — LLM 없이 사실 문장으로 답한다: {text}")
            self._say(gated, "대체-위험질문", facts, tool_q, m)
            return
        sensed = voice_card.sensor_answer(text, facts)
        if sensed:
            # 🔑 이 시스템은 장비 센서를 보지 않는다 — LLM 에 맡길 이유가 없다(설계 2026-10-04 §4.5-나)
            log(f"장비 센서 질문 — LLM 없이 「확인할 수 없음」으로 답한다: {text}")
            self._say(sensed, "대체-센서질문", facts, tool_q, m)
            return
        if not self.llm.available():
            m["LLM오류"] = "예열 전" if not self.llm.ready else "건너뜀(연속 실패)"
            self._answer_fixed(tool_q, facts, "고정-LLM준비안됨", m)
            return
        card = voice_card.build_card(state, dets, fresh, question=text)   # 🔑 끝났냐 질문이면 「질문한 일」 줄
        m["카드줄수"] = card.count("\n")
        th, box = ask_async(self.llm.ask, card, text)
        if not self._preempted(m):
            self.spk.play("checking", self.alog)     # 🔑 LLM 과 겹쳐 돈다
        th.join(timeout=config.LLM_TIMEOUT_SEC + 2.0)
        raw, lm = box.get("r", (None, {"LLM오류": "스레드 미완"}))
        m.update(lm)
        if self._preempted(m):
            return
        if not raw:
            self._answer_fixed(tool_q, facts, "고정-폴백", m)
            return
        said, src, bad = voice_card.finalize(raw, facts, question=text)
        m.update({"LLM원문": raw, "다듬은문장": said})
        if bad:
            m["안전규칙"] = bad
            log(f"⚠️ 안전 규칙 {bad} — 대체 문장으로 답한다: {raw}")
        if not said:
            self._answer_fixed(tool_q, facts, "고정-빈답", m)
            return
        self._say(said, src, facts, tool_q, m)

    def _say(self, said, src, facts, tool_q, m):
        """합성 → 한도 → 검산 → 전송.

        🔴 **검산은 합성 뒤·전송 앞이다**(설계 §7) — 재생에 가장 가까운 시점일수록 판단이 정확하다.
        """
        got = self.tts.synth(said)
        if not got:
            self._answer_a(tool_q, "고정-합성실패", m)
            return
        pcm, rate, sec = got
        n = len(pcm) // 2
        if not voice_tts.fits(n, rate):
            m["한도초과"] = [n, rate]
            log(f"🔴 답이 펌웨어 한도를 넘는다({n}샘플 · {rate}Hz) — 보내지 않고 A 갈래로: {said}")
            self._answer_a(tool_q, "고정-한도초과", m)
            return
        dets2, fresh2 = self._read_tools()
        now2 = voice_card.card_facts(self._read_state(), dets2, fresh2)
        ok_v, bad = voice_card.verify_answer(said, facts, now2)
        m["검산"] = bad or "일치"
        if not ok_v:
            # 🔑 공구를 물었던 것이면 새 상태의 공구 답이 더 쓸모 있다.
            log(f"⚠️ 검산 불일치 {bad} — 합성한 소리를 버린다: {said}")
            key = answer_key(dets2, fresh2) if (tool_q and bad == ["공구"]) else "changed"
            self._play_key(key, "고정-검산불일치", m, 버린문장=said)
            return
        if self._preempted(m):
            return
        VLOG.event("answer", src=src, text=said)     # 보내기 직전
        t_p = time.time()
        resp = self.spk.send(voice_tts.frame(pcm, rate), expect=True, still_valid=lambda: not self._stale())
        if resp is DROPPED:
            m["답변출처"] = "알림으로버림"
            log("보내기 직전에 알림·비상 상황 — 만들던 답을 버린다")
            return
        ok = bool(resp) and any("재생 완료" in r for r in resp)
        stopped = bool(resp) and any("재생 중단" in r for r in resp)     # 알림·해제가 멈췄다 — 실패가 아니다
        self.alog.played_pcm("llm", pcm, rate, said)
        m.update({"답변출처": src, "답변문장": said, "말하는초": round(sec, 2),
                  "재생성공": ok, "재생중단": stopped, "재생_ms": round((time.time() - t_p) * 1000)})
        if ok or stopped:
            log(f"{src} 답변({sec:.1f}초 말함{' · 도중에 멈춤' if stopped else ''}) → {said}")
            return
        log(f"🔴 답 재생이 확인되지 않았다 — A 갈래로 한 번 더: {said}")
        m["답변재생실패"] = said
        self._answer_a(tool_q, "고정-재생실패대체", m)

    def _answer_fixed(self, tool_q, facts, src, m):
        """LLM 이 답을 못 낼 때 — 「지금 할 일」(공구 질문이면 공구 상황) 문장을 합성해 말한다(설계 2026-10-04 §4.6).

        🔑 공구 질문인데 공구 상황이 없으면 종전처럼 녹음(A 갈래) — 「지금은 공구를 확인하는 단계가 아닙니다」가 정확하다.
        🔴 합성·재생이 실패하면 `_say` 가 A 갈래로 떨어진다 — 「모든 실패의 착지점은 A」는 그대로다.
        """
        if tool_q and not facts.get("공구상황"):
            self._answer_a(tool_q, src, m)
            return
        said = voice_card.fallback_sentence(facts, tool_q=tool_q)
        if not said:
            self._answer_a(tool_q, src, m)
            return
        self._say(said, src, facts, tool_q, m)

    def _answer_a(self, tool_q, src, m, any_question=False):
        """A 갈래(고정 wav). 🔴 공구는 폴백 직전에 다시 읽는다 — 질문 때 것은 15초 전일 수 있다(R3 M2)."""
        dets, fresh = self._read_tools()
        key = answer_key(dets, fresh) if (tool_q or any_question) else "unavailable"
        self._play_key(key, src, m)

    def _play_key(self, key, src, m, **extra):
        if self._preempted(m):
            return
        VLOG.event("answer", src=src, key=key)       # 고정 답 소리 — 보내기 직전
        t_p = time.time()
        ok = self.spk.play(key, self.alog, still_valid=lambda: not self._stale())
        m.update({"답변출처": src, "답변": key, "재생성공": ok,
                  "재생중단": bool(getattr(self.spk, "last_stopped", False)),
                  "재생_ms": round((time.time() - t_p) * 1000), **extra})


def handle_utterance(bot, stt, alog, seg):
    """잘라낸 발화 하나 — STT · 계측 · 판단. 질문에 답했으면 True."""
    samples = seg.tolist()
    gen0 = bot.alert_gen()                 # 🔑 받아쓰기 전 — 받아쓰는 사이 알림이 나갔으면 이 질문은 낡았다
    t_stt = time.time()
    t_stt_m = time.monotonic()             # 받아쓰기를 시작한 시각 = 발화가 끝난 때(측정 기록 stt)
    text = stt(samples)
    m = {
        "t": ms_clock(),
        "발화초": round(len(samples) / RATE, 2),
        "발화RMS": round(vl_rms(samples)),
        "노이즈바닥": round(noise_floor(seg, RATE)),
        "STT텍스트": text,
        "STT_ms": round((time.time() - t_stt) * 1000),
    }
    alog.utterance(samples, text)
    if not text.strip():
        m["판정"] = "빈 결과"
        VLOG.event("stt", t=t_stt_m, text=text, stt_ms=m["STT_ms"], utter_sec=m["발화초"])
        metric(m)
        return False
    log(f"들림: {text}")
    # 🔑 판단(on_text) 전에 — 판단이 실패해도 남고, 답·재생 사건보다 앞에 쌓인다(리뷰 M-3)
    VLOG.event("stt", t=t_stt_m, text=text, stt_ms=m["STT_ms"], utter_sec=m["발화초"])
    answered = bot.on_text(text, m, gen0=gen0)
    metric(m)
    return answered


def run(get_ip, once=False, mic_port=MIC_PORT, cmd_port=CMD_PORT, stt=None,
        tts=_AUTO, llm=_AUTO, read_state=None, read_tools=None, stop=None):
    """데몬 본체. `stt`·`tts`·`llm`·`read_*`·`stop` 은 시험이 넣는다(없으면 실제 모델·파일)."""
    global VLOG
    VLOG = measure_log.open_from_env(["voice_events"], event_file="voice_events", log=log)
    if stt is None:
        log("STT 적재 중...")
        rec = build_stt()
        stt = lambda samples: transcribe(rec, samples)      # noqa: E731
        log("STT 준비됨")
    if tts is _AUTO:
        tts = load_tts()
    if llm is _AUTO:
        llm = voice_llm.LlmClient(log=log) if config.LLM_ENABLED else None
    alog = open_audio_log(AUDIO_DIR)
    if AUDIO_DIR:
        log(f"오디오 기록 → {AUDIO_DIR}")
    spk = Speaker(get_ip, cmd_port)
    mic = MicReceiver(get_ip, mic_port, rate=RATE, stall_sec=STALL_SEC, retry_sec=RETRY_SEC,
                      lag_limit=LAG_LIMIT, max_queue_sec=WINDOW_SEC + LAG_LIMIT,
                      on_chunk=alog.mic, log=log, once=once)
    if llm is not None:
        # 🔑 켜자마자 배경에서 데운다 — 콜드는 질문으로는 안 데워진다(R3 C2 · D1)
        llm.start_warm(on_done=lambda ok, m: log(ready_line(mic, spk, tts, llm)))
    # 🔑 명령 채널을 미리 붙여 둔다 — 첫 「띠링」이 연결 설정과 겹쳐 안 들렸다(2026-09-07).
    spk.send(b"")
    mic.start()                       # 🔑 데몬을 ESP32 보다 먼저 켜도 된다 — 붙을 때까지 다시 시도한다
    stop_ev = stop if stop is not None else threading.Event()
    alerts = AlertWatcher(spk, read_state=read_state, alog=alog) if config.VOICE_ALERTS else None
    if alerts is not None:
        alerts.start(stop_ev)                    # 🔑 메인 루프와 따로(설계 2026-10-04 §4.3)
    bot = Assistant(spk, tts, llm, alog, read_state=read_state, read_tools=read_tools,
                    alert_gen=(lambda: alerts.gen) if alerts is not None else None)
    seen_alert = 0
    up_at = 0.0                       # 업링크 바이트 사건(10초마다)을 마지막으로 남긴 때
    errs = 0                          # 이어진 오류 수 — 답을 마친 발화가 있으면 0
    buf = np.zeros(0, dtype=np.int16)
    since, gen = 0, 0
    hop = int(RATE * VAD_HOP_SEC)
    try:
        while not stop_ev.is_set():
            try:
                if VLOG.enabled and time.monotonic() - up_at >= 10:     # 업링크 누적 바이트(측정 V9)
                    up_at = time.monotonic()
                    vev_uplink(mic.bytes_total, mic.connected)
                if mic.closed:
                    log("업링크 종료 — 리허설 끝")
                    return
                if not mic.alive():
                    log("🔴 마이크 수신 스레드가 죽었다 — 데몬을 끝낸다(run_voice.sh --forever 가 다시 띄운다)")
                    return
                if mic.generation != gen:
                    if gen or spk.s is None:
                        # 🔑 다시 붙었거나, 보드보다 데몬이 먼저 켜져 시작 때 못 붙었으면 명령 채널을 미리 붙인다
                        #    — 첫 띠링 유실(Q3 · R2 I1 · 최종 리뷰 I3: 상시 가동에선 데몬이 먼저 뜨는 것이 기본 순서)
                        spk.reset()
                        spk.send(b"")
                    gen = mic.generation
                    buf, since = np.zeros(0, dtype=np.int16), 0
                    log(ready_line(mic, spk, tts, llm))
                hold, seen_alert = alert_hold(alerts, seen_alert)
                if hold:
                    # 🔑 알림을 내보내는 동안·직후 들어온 소리는 버리고 대화창을 닫는다 — 알림을 질문으로
                    #    받아쓰지 않게 · 알림 뒤는 비상 상황이라 해제 전까지 질문을 받지 않는다(사용자 2026-10-04 · §4.7)
                    mic.clear()
                    buf, since = np.zeros(0, dtype=np.int16), 0
                    bot.awake_until = 0.0
                    time.sleep(0.02)
                    continue
                new = mic.pull()
                if len(new) == 0:
                    time.sleep(0.02)
                    continue
                buf = np.concatenate((buf, new))
                since += len(new)
                limit = int(RATE * (WINDOW_SEC + LAG_LIMIT))
                if len(buf) > limit:
                    # 🔴 최신 우선 — 링크가 막혔다 한꺼번에 터지면(fake_glass --burst) 오래된 것을 버린다
                    dropped = len(buf) - int(RATE * WINDOW_SEC)
                    buf = buf[dropped:]
                    log(f"⚠️ 오디오가 밀려 {dropped / RATE:.1f}초를 버렸다(최신 우선)")
                if since < hop or len(buf) < RATE * 0.8:
                    continue
                since = 0
                seg = find_utterance(buf, RATE)
                if seg is None:
                    if len(buf) > RATE * WINDOW_SEC:       # 무음만 길게 쌓이면 앞을 잘라 둔다
                        buf = buf[len(buf) - int(RATE * 1.0):]
                    continue
                s, e = seg
                if len(buf) - e < int(RATE * QUIET_TAIL):  # 발화가 아직 안 끝났다
                    continue
                seg_samples, buf = buf[s:e], buf[e:]
                answered = handle_utterance(bot, stt, alog, seg_samples)
                errs = 0
                if answered:
                    # 🔴 대답하는 동안 들어온 소리를 버린다 — 답 반향·늦은 호출어가 다음 발화로 잡혀
                    #    엉뚱한 띠링·헛답이 났다(G11 · R3 I3). 시각 = 답이 끝난 지금까지.
                    n = mic.clear()
                    buf = np.zeros(0, dtype=np.int16)
                    if n:
                        log(f"대답하는 동안 들어온 소리 {n / RATE:.1f}초를 버렸다(G11)")
                    if once:
                        log("리허설 목표 달성")
                        return
            except Exception as e:                         # noqa: BLE001
                # 🔴 예외 하나로 시연 내내 데몬이 없으면 안 된다(R2 M8) — 그 발화만 버리고 계속한다
                errs += 1
                if errs >= MAIN_ERR_LIMIT:
                    # 🔴 같은 오류가 발화마다 이어지면(STT 가 매번 실패) 버티는 것이 귀먹음이다 — 끝내면
                    #    run_voice.sh --forever 가 모델을 새로 올린다(1단계 M3)
                    log(f"🔴 메인 루프 오류가 {errs}번 연속 — 데몬을 끝낸다(감시가 다시 띄운다): {type(e).__name__}: {e}")
                    return
                log(f"🔴 메인 루프 오류 — 이 발화만 버리고 계속한다: {type(e).__name__}: {e}")
                buf, since = np.zeros(0, dtype=np.int16), 0
                time.sleep(0.5)
    finally:
        stop_ev.set()                     # 상태 감시 스레드를 끝낸다
        mic.stop()
        VLOG.close()                      # 🔑 데몬이 다시 떠도 MeasureLog 가 이어 쓴다(머리줄은 한 번)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", help="ESP32 주소 (기본: Demo/.camera_ip 를 붙을 때마다 다시 읽는다)")
    ap.add_argument("--once", action="store_true",
                    help="답변을 한 번 내보내면 끝낸다 (오프라인 리허설용)")
    a = ap.parse_args()
    lock = take_lock()                                      # noqa: F841 — 끝날 때까지 쥐고 있는다
    if lock is None:
        log(f"🔴 음성비서가 이미 돈다({LOCK_FILE}) — 명령 채널은 손님 하나라 둘이 돌면 서로 끊는다. 끝낸다")
        sys.exit(EXIT_ALREADY_RUNNING)
    get_ip = (lambda: a.ip) if a.ip else esp_ip
    log(f"ESP32 = {get_ip()}")       # 🔴 주소 파일이 없으면 여기서 이유와 함께 끝난다
    if os.environ.get("SOP_MEASURE_DIR"):
        exit_on_sigterm()
    try:
        run(get_ip, once=a.once)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
