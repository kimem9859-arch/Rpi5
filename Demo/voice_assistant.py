#!/usr/bin/env python3
"""음성비서 데몬 — 「가디언」 → 띠링 → 「앞에 보이는 게 뭐야?」 → 공구 안내.

실행: ./Demo/run_voice.sh          (= ~/env/tts/.venv/bin/python Demo/voice_assistant.py)
정본: ../docs/superpowers/specs/2026-09-06-음성비서-시연구현-design.md

🔑 GUI 를 0줄도 건드리지 않는다 — 별도 프로세스이고, 공구 정보는 tool_worker 가
   이미 쓰는 /dev/shm/sop_tool/resp.json 을 읽기만 한다.

🔴 접속 주소는 Demo/.camera_ip 를 매번 읽는다 — mDNS 를 쓰지 않기로 했고
   (통신경로 설계 §6-②), 그 덕에 iptime·폰·파이AP 어느 폴백에서도 그대로 돈다.

🔴 이 코드는 실HW 에서 아직 돌아본 적이 없다(2026-09-06 시점). 오프라인
   리허설(Demo/test/fake_glass.py)로 배선만 확인했다. 촬영 당일 첫 기동에서
   문제가 나면 Demo/voice/시연절차.md 의 증상별 대응표를 본다.
"""
import argparse
import array
import os
import socket
import struct
import sys
import time
import wave

_DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DEMO_DIR)

from voice_lib import (answer_key, find_utterance, is_tool_question, is_wake,
                       read_tool_dets)

IP_FILE  = os.path.join(_DEMO_DIR, ".camera_ip")
WAV_DIR  = os.path.join(_DEMO_DIR, "voice", "wav")
MIC_PORT = 8889
CMD_PORT = 8890
RATE     = 16000

STT_DIR   = os.path.expanduser("~/env/tts/sherpa-onnx-zipformer-korean-2024-06-24")
HOTWORDS  = os.path.expanduser("~/lab/tts/hotwords_ko.txt")
BPE_VOCAB = os.path.expanduser("~/lab/tts/bpe.vocab")

WINDOW_SEC = 6.0      # 판정에 쓰는 최근 구간
LISTEN_SEC = 8.0      # 🔑 호출 뒤 질문을 기다리는 시간 — 없으면 영원히 깨어 있다
LAG_LIMIT  = 2.0      # 🔴 이보다 밀리면 오래된 오디오를 버린다(최신 우선)
QUIET_TAIL = 0.4      # 발화가 끝났다고 보기까지 필요한 뒤쪽 무음


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def esp_ip():
    return open(IP_FILE, encoding="utf-8").read().strip()


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


class Speaker:
    """명령 채널(8890) — 한 번 붙여 두고 계속 쓴다.

    🔑 매번 새로 붙지 않는 이유 — 펌웨어가 손님 하나를 붙들고 있어서, 끊었다
       붙이면 그 사이 명령이 샐 수 있다.
    """

    def __init__(self, ip):
        self.ip = ip
        self.s = None

    def _ensure(self):
        if self.s is None:
            self.s = socket.create_connection((self.ip, CMD_PORT), 10)
            self.s.settimeout(30)
            log(f"명령 채널 연결됨 ({CMD_PORT})")

    def send(self, payload):
        for attempt in (1, 2):
            try:
                self._ensure()
                self.s.sendall(payload)
                return True
            except OSError as e:
                log(f"🔴 명령 전송 실패({attempt}): {e}")
                try:
                    if self.s:
                        self.s.close()
                except OSError:
                    pass
                self.s = None
        return False

    def chime(self):
        return self.send(b"B\n")

    def play(self, key):
        body, sec = wav_payload(os.path.join(WAV_DIR, f"{key}.wav"))
        ok = self.send(body)
        log(f"재생 → {key} ({sec:.1f}초)" if ok else f"🔴 재생 실패 → {key}")
        return ok


def run(ip, once=False, a_ip=None):
    log(f"ESP32 = {ip}")
    log("STT 적재 중...")
    rec = build_stt()
    log("STT 준비됨")

    spk = Speaker(ip)
    mic = socket.create_connection((ip, MIC_PORT), 10)
    mic.settimeout(5)
    log(f"마이크 업링크 연결됨 ({MIC_PORT})")

    buf = array.array("h")
    awake_until = 0.0

    while True:
        try:
            chunk = mic.recv(16384)
        except socket.timeout:
            continue
        if not chunk:
            if once:
                log("업링크 종료 — 리허설 끝")
                return
            log("🔴 업링크 끊김 — 3초 뒤 재연결")
            mic.close()
            time.sleep(3)
            ip = a_ip or esp_ip()   # 🔴 --ip 로 준 주소를 잃지 않는다
            mic = socket.create_connection((ip, MIC_PORT), 10)
            mic.settimeout(5)
            buf = array.array("h")
            continue

        a = array.array("h")
        a.frombytes(chunk[:len(chunk) // 2 * 2])
        buf.extend(a)

        # 🔴 최신 우선 — TCP 재전송으로 밀리면 오래된 것을 버린다.
        #    카메라가 CAMERA_GRAB_LATEST 로 같은 문제를 푸는 것과 같은 처방.
        limit = int(RATE * (WINDOW_SEC + LAG_LIMIT))
        if len(buf) > limit:
            dropped = len(buf) - int(RATE * WINDOW_SEC)
            del buf[:dropped]
            log(f"⚠️ 오디오가 밀려 {dropped / RATE:.1f}초를 버렸다(최신 우선)")

        if len(buf) < RATE * 0.8:
            continue

        seg = find_utterance(buf.tolist(), RATE)
        if seg is None:
            # 무음만 길게 쌓이면 앞을 잘라 둔다
            if len(buf) > RATE * WINDOW_SEC:
                del buf[:len(buf) - int(RATE * 1.0)]
            continue
        s, e = seg
        # 발화가 아직 끝나지 않았으면(끝이 버퍼 끝에 붙어 있음) 더 기다린다
        if len(buf) - e < int(RATE * QUIET_TAIL):
            continue

        text = transcribe(rec, buf[s:e].tolist())
        del buf[:e]
        if not text.strip():
            continue
        log(f"들림: {text}")

        now = time.time()
        awake = now < awake_until

        if is_wake(text):
            spk.chime()
            awake_until = now + LISTEN_SEC
            awake = True
            log("호출어 인식 → 띠링")
            # 🔑 한 문장에 질문까지 있으면 바로 답한다(상태기계 폴백).
            #    "가디언, 앞에 보이는 게 뭐야?" 를 한 번에 말해도 동작한다.

        if awake and is_tool_question(text):
            dets, fresh = read_tool_dets()
            key = answer_key(dets, fresh)
            log(f"공구 {len(dets)}개 · 신선 {fresh} → {key}")
            spk.play(key)
            awake_until = 0.0
            if once:
                log("리허설 목표 달성")
                return


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", help="ESP32 주소 (기본: Demo/.camera_ip)")
    ap.add_argument("--once", action="store_true",
                    help="답변을 한 번 내보내면 끝낸다 (오프라인 리허설용)")
    a = ap.parse_args()
    try:
        run(a.ip or esp_ip(), once=a.once, a_ip=a.ip)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
