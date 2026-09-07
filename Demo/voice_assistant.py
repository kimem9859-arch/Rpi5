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
import json
import os
import socket
import struct
import sys
import time
import wave

_DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DEMO_DIR)

from voice_lib import (answer_key, find_utterance, is_tool_question, is_wake,
                       noise_floor, read_tool_dets)
from voice_lib import rms as vl_rms

# 🔑 보드가 둘이다(2026-09-06 결정) — 메인=카메라(.camera_ip) / 서브=오디오(.audio_ip).
#    .audio_ip 가 없으면 한 보드 구성으로 보고 .camera_ip 를 쓴다.
AUDIO_IP_FILE = os.path.join(_DEMO_DIR, ".audio_ip")
IP_FILE       = os.path.join(_DEMO_DIR, ".camera_ip")
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
LAG_LIMIT  = 2.0      # 🔴 이보다 밀리면 오래된 오디오를 버린다(최신 우선)
QUIET_TAIL = 0.4      # 발화가 끝났다고 보기까지 필요한 뒤쪽 무음
VOLUME     = 5        # 🔑 펌웨어 음량 1~5. 기본 3 은 실청취에서 작았다(2026-09-07)

# 🔑 보고서 시각자료용 계측 — 발화마다 한 줄씩 JSONL 로 남긴다.
#    환경변수 SOP_VOICE_METRICS 로 경로를 준다(없으면 안 남긴다).
METRICS_PATH = os.environ.get("SOP_VOICE_METRICS")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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


def esp_ip():
    """오디오 보드 주소. `.audio_ip` 가 있으면 그것, 없으면 `.camera_ip`.

    🔴 mDNS 를 쓰지 않으므로(통신경로 설계 §6-②) 주소는 파일이 정본이고,
       매번 다시 읽어 통신경로 폴백(iptime→폰→파이AP)을 따라간다.
    """
    for path in (AUDIO_IP_FILE, IP_FILE):
        try:
            ip = open(path, encoding="utf-8").read().strip()
            if ip:
                return ip
        except OSError:
            continue
    raise SystemExit(f"🔴 오디오 보드 주소를 못 찾았다 — {AUDIO_IP_FILE} 를 만들어라")


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


def connect_mic(ip_getter, retry_sec=3.0):
    """마이크 업링크에 붙는다 — 될 때까지 다시 시도한다.

    🔴 예전에는 `socket.create_connection` 이 try 밖에 있어, 끊긴 뒤 ESP32 가
       아직 안 살아났으면 `ConnectionRefusedError` 로 **프로세스가 통째로 죽었다**
       (2026-09-06 교차 리허설, 세션 73cfe23a 가 발견). 촬영 중이면 재시작해야
       하는 자리라 반드시 살아남아야 한다.

    🔑 주소를 함수로 받는 이유 — 재시도마다 `.camera_ip` 를 다시 읽어야
       통신경로 폴백(iptime→폰→파이AP)을 따라갈 수 있다.
    """
    while True:
        ip = ip_getter()
        try:
            s = socket.create_connection((ip, MIC_PORT), 10)
            s.settimeout(5)
            log(f"마이크 업링크 연결됨 ({ip}:{MIC_PORT})")
            return s
        except OSError as e:
            log(f"🔴 업링크 연결 실패 ({ip}:{MIC_PORT}) {e} — {retry_sec:.0f}초 뒤 재시도")
            time.sleep(retry_sec)


class Speaker:
    """명령 채널(8890) — 한 번 붙여 두고 계속 쓴다.

    🔑 매번 새로 붙지 않는 이유 — 펌웨어가 손님 하나를 붙들고 있어서, 끊었다
       붙이면 그 사이 명령이 샐 수 있다.
    """

    def __init__(self, ip):
        self.ip = ip
        self.s = None
        self.f = None

    def _ensure(self):
        if self.s is None:
            self.s = socket.create_connection((self.ip, CMD_PORT), 10)
            self.s.settimeout(30)
            self.f = self.s.makefile("rb")
            # 🔑 음량을 붙을 때마다 올린다 — 펌웨어 기본은 3단계(진폭 6000)인데
            #    2026-09-07 실청취에서 **작아서 잘 안 들렸다.** 5단계(13000)로 올리니
            #    "무슨 말인지 들릴 정도"가 됐다(⛔ §10.49 판정 통과).
            #    ⚠️ 배터리 구동에서는 소비가 늘어 슬라이드 스위치 정격(0.3A)에 붙는다
            #       (설계 §5.4) — 시연은 짧아 감수하지만, 상시 운용이면 낮춘다.
            self.s.sendall(f"{VOLUME}\n".encode())
            log(f"명령 채널 연결됨 ({CMD_PORT}) · 음량 {VOLUME}단계")

    def _drain(self, wait=15.0):
        """펌웨어 응답을 읽어 돌려준다 — 🔑 **보냈다 ≠ 들렸다**.

        🔴 2026-09-07 에 물렸다 — 데몬은 보내기만 하고 응답을 안 봐서, 로그에는
           「재생 → wrench」가 찍혔는데 소리는 안 났다. 무엇이 어긋났는지 알 길이
           없었다. 펌웨어는 「[적재] … ok」·「[재생 완료]」를 돌려주므로 그것을
           확인해 기록한다.
        ⚠️ 재생은 동기라 응답이 소리 길이만큼 늦게 온다 — 그동안 마이크 버퍼가
           쌓이지만 「최신 우선」이 정리한다.
        """
        out = []
        end = time.time() + wait
        self.s.settimeout(1.0)
        while time.time() < end:
            try:
                line = self.f.readline()
            except (OSError, AttributeError):
                break
            if not line:
                break
            t = line.decode("utf-8", "replace").strip()
            if t:
                out.append(t)
                if "재생 완료" in t or "FAIL" in t:
                    break
        self.s.settimeout(30)
        return out

    def send(self, payload, expect=False):
        for attempt in (1, 2):
            try:
                self._ensure()
                self.s.sendall(payload)
                if expect:
                    return self._drain()
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

    def reset(self):
        """링크가 끊겼을 때 명령 채널도 버린다 — 다음 send 에서 다시 붙는다."""
        if self.s is not None:
            try:
                self.s.close()
            except OSError:
                pass
            self.s = None

    def chime(self):
        return self.send(b"B\n")

    def play(self, key):
        body, sec = wav_payload(os.path.join(WAV_DIR, f"{key}.wav"))
        resp = self.send(body, expect=True)
        ok = bool(resp) and any("재생 완료" in r for r in resp)
        if ok:
            log(f"재생 → {key} ({sec:.1f}초) · ESP32 확인됨")
        else:
            log(f"🔴 재생이 확인되지 않았다 → {key} · 응답={resp}")
        return ok


def run(ip, once=False, a_ip=None):
    log(f"ESP32 = {ip}")
    log("STT 적재 중...")
    rec = build_stt()
    log("STT 준비됨")

    spk = Speaker(ip)
    # 🔑 명령 채널을 미리 붙여 둔다 — 첫 「띠링」이 연결 설정과 겹쳐 안 들렸다
    #    (2026-09-07 실측: 로그에는 나갔는데 귀로는 안 들렸다).
    spk.send(b"")
    # 🔑 데몬을 ESP32 보다 먼저 켜도 된다 — 붙을 때까지 기다린다.
    get_ip = (lambda: a_ip) if a_ip else esp_ip
    mic = connect_mic(get_ip)

    buf = array.array("h")
    awake_until = 0.0

    while True:
        try:
            chunk = mic.recv(16384)
        except socket.timeout:
            continue
        except OSError as e:
            # 🔴 끊김은 빈 청크로만 오지 않는다 — reset by peer 도 여기로 온다.
            log(f"🔴 업링크 오류: {e}")
            chunk = b""
        if not chunk:
            if once:
                log("업링크 종료 — 리허설 끝")
                return
            log("🔴 업링크 끊김 — 다시 붙는다")
            try:
                mic.close()
            except OSError:
                pass
            time.sleep(3)
            mic = connect_mic(get_ip)
            buf = array.array("h")
            spk.reset()          # 명령 채널도 다시 잡게 한다
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

        seg_samples = buf[s:e].tolist()
        t_stt = time.time()
        text = transcribe(rec, seg_samples)
        stt_ms = (time.time() - t_stt) * 1000
        m = {
            "t": time.strftime("%H:%M:%S"),
            "발화초": round((e - s) / RATE, 2),
            "발화RMS": round(vl_rms(seg_samples)),
            "노이즈바닥": round(noise_floor(seg_samples, RATE)),
            "STT텍스트": text,
            "STT_ms": round(stt_ms),
        }
        del buf[:e]
        if not text.strip():
            m["판정"] = "빈 결과"
            metric(m)
            continue
        log(f"들림: {text}")

        now = time.time()
        awake = now < awake_until
        m["호출어"] = is_wake(text)
        m["공구질문"] = is_tool_question(text)

        if is_wake(text):
            t_c = time.time()
            spk.chime()
            m["띠링_ms"] = round((time.time() - t_c) * 1000)
            awake_until = now + LISTEN_SEC
            awake = True
            log("호출어 인식 → 띠링")
            # 🔑 한 문장에 질문까지 있으면 바로 답한다(상태기계 폴백).
            #    "가디언, 앞에 보이는 게 뭐야?" 를 한 번에 말해도 동작한다.

        if awake and is_tool_question(text):
            dets, fresh = read_tool_dets()
            key = answer_key(dets, fresh)
            log(f"공구 {len(dets)}개 · 신선 {fresh} → {key}")
            t_p = time.time()
            ok = spk.play(key)
            m.update({"공구수": len(dets), "공구신선": fresh, "답변": key,
                      "재생_ms": round((time.time() - t_p) * 1000), "재생성공": ok,
                      "검출": [[str(d[0]), round(float(d[1]), 2)] for d in dets]})
            awake_until = 0.0
            metric(m)
            if once:
                log("리허설 목표 달성")
                return
            continue
        metric(m)


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
