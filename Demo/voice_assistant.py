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
import shutil
import sys
import threading
import time
import wave

_DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DEMO_DIR)

from voice_lib import (answer_key, find_utterance, is_tool_question, is_wake,
                       noise_floor, read_tool_dets)
from voice_lib import rms as vl_rms

import config
import voice_card
import voice_llm
import voice_tts

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

# 🔑 보고서용 오디오 기록 — 환경변수 SOP_VOICE_AUDIO 로 폴더를 준다(없으면 안 남긴다).
#    귀에 들린 것과 기계가 받은 것을 나중에 대조할 수 있어야 한다.
#      마이크_전체.wav      ESP32 가 보낸 업링크 전부(16kHz)
#      발화_NNN.wav / .txt  잘라낸 발화 구간과 그 STT 결과
#      재생_NNN_<키>.wav    스피커로 내보낸 것(사전 합성된 TTS 원본)
AUDIO_DIR = os.environ.get("SOP_VOICE_AUDIO")


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
        if self.full:
            self.full.writeframes(array.array("h", samples).tobytes())

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
            except socket.timeout:
                # 🔴 재생 중에는 펌웨어가 몇 초간 아무것도 안 보낸다 — 여기서
                #    포기하면 「확인되지 않았다」로 잘못 판정한다(2026-09-07 에
                #    실제로 그랬다. 소리는 났는데 로그만 실패로 남았다).
                continue
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

    def play(self, key, alog=None):
        path = os.path.join(WAV_DIR, f"{key}.wav")
        if alog:
            alog.played(key, path)
        body, sec = wav_payload(path)
        resp = self.send(body, expect=True)
        ok = bool(resp) and any("재생 완료" in r for r in resp)
        if ok:
            log(f"재생 → {key} ({sec:.1f}초) · ESP32 확인됨")
        else:
            log(f"🔴 재생이 확인되지 않았다 → {key} · 응답={resp}")
        return ok


def ask_async(card, question):
    """LLM 을 배경에서 부른다 — 「확인 중」 재생과 겹치게 하려는 것이다.

    🔴 순서대로 하면 재생 2초가 지연에 그대로 더해진다. 명령 채널이 하나뿐이라
       (`Speaker`) 재생 완료를 기다리는 동안 메인 루프가 막히기 때문이다.
       먼저 띄워 두면 그 2초가 LLM 시간에 흡수된다(설계 §7).
    """
    box = {}

    def _work():
        box["r"] = voice_llm.ask(card, question)

    th = threading.Thread(target=_work, daemon=True)
    th.start()
    return th, box


def run(ip, once=False, a_ip=None):
    log(f"ESP32 = {ip}")
    log("STT 적재 중...")
    rec = build_stt()
    log("STT 준비됨")

    tts = None
    if config.LLM_ENABLED:
        try:
            from voice_tts import Tts
            tts = Tts()
            log("런타임 TTS 준비됨")
        except Exception as e:                 # noqa: BLE001
            log(f"🔴 런타임 TTS 를 못 올렸다 — 고정 wav 로만 답한다: {e}")

    alog = AudioLog(AUDIO_DIR)
    if AUDIO_DIR:
        log(f"오디오 기록 → {AUDIO_DIR}")
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
        alog.mic(a)

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
        alog.utterance(seg_samples, text)
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
            state = voice_card.read_state()
            facts = voice_card.card_facts(state, dets, fresh)
            m.update({"공구수": len(dets), "공구신선": fresh,
                      "검출": [[str(d[0]), round(float(d[1]), 2)] for d in dets],
                      "단계": facts["단계"], "세션": facts["세션"]})

            # ── ① 작업 전이면 LLM 을 안 태운다 ────────────────────────────
            #    카드가 비어 있어 LLM 이 할 말 자체가 없다. 5~7초를 기다릴
            #    이유가 없고, 없는 상태를 지어낼 위험만 생긴다(유형 ⑤).
            if not facts["세션"]:
                t_p = time.time()
                ok = spk.play("notready", alog)
                m.update({"답변출처": "고정-작업전", "답변": "notready",
                          "재생_ms": round((time.time() - t_p) * 1000), "재생성공": ok})
                awake_until = 0.0
                metric(m)
                continue

            # ── ② LLM 갈래 ────────────────────────────────────────────────
            said = None
            llm_on = config.LLM_ENABLED and tts is not None
            m["LLM사용"] = llm_on
            if llm_on:
                card = voice_card.build_card(state, dets, fresh)
                m["카드줄수"] = card.count("\n")
                th, box = ask_async(card, text)
                try:
                    spk.play("checking", alog)     # 🔑 LLM 과 겹쳐 돈다
                    th.join(timeout=config.LLM_TIMEOUT_SEC + 2.0)
                    said, lm = box.get("r", (None, {"LLM오류": "스레드 미완"}))
                    m.update(lm)
                finally:
                    # 🔴 기다리는 5~7초 동안 쌓인 소리를 버린다(최신 우선).
                    #    안 버리면 밀린 소리가 곧바로 다음 발화로 잡혀,
                    #    답이 끝나자마자 엉뚱한 답이 또 나간다. ← G11 의 실체
                    del buf[:]

            # ── ③ 합성 → 검산 → 전송 ────────────────────────────────────
            #    🔴 **검산은 합성 뒤·전송 앞이다**(설계 §7). 재생에 가장 가까운
            #       시점일수록 판단이 정확하다. 검산에 걸리면 이미 합성한
            #       0.4~1.05초를 버리게 되지만, **어긋난 답을 내보내는 것보다 싸다.**
            t_p = time.time()
            got = tts.synth(said) if said else None
            if got:
                pcm, rate, sec = got
                dets2, fresh2 = read_tool_dets()
                now2 = voice_card.card_facts(voice_card.read_state(), dets2, fresh2)
                ok_v, bad = voice_card.verify_answer(said, facts, now2)
                m["검산"] = bad or "일치"
                if ok_v:
                    resp = spk.send(voice_tts.frame(pcm, rate), expect=True)
                    ok = bool(resp) and any("재생 완료" in r for r in resp)
                    alog.played_pcm("llm", pcm, rate, said)
                    m.update({"답변출처": "LLM", "답변문장": said,
                              "말하는초": round(sec, 2), "재생성공": ok})
                    log(f"LLM 답변({sec:.1f}초 말함) → {said}")
                else:
                    # 🔑 공구를 물었던 것이면 새 상태의 공구 답이 더 쓸모 있다.
                    log(f"⚠️ 검산 불일치 {bad} — 합성한 소리를 버린다: {said}")
                    key = answer_key(dets2, fresh2) if bad == ["공구"] else "changed"
                    ok = spk.play(key, alog)
                    m.update({"답변출처": "고정-검산불일치", "답변": key,
                              "버린문장": said, "재생성공": ok})
            else:
                if said:
                    key, src = "unavailable", "고정-합성실패"
                elif llm_on:
                    key, src = "unavailable", "고정-폴백"
                else:
                    # 🔴 LLM 을 안 쓰는 구성(SOP_LLM=0 · TTS 적재 실패)이면 A 갈래
                    #    그대로 답한다 — 「답변할 수 없습니다」는 기능이 아예 없다는
                    #    뜻이 되어 시연에서 더 나쁘다.
                    key, src = answer_key(dets, fresh), "고정-LLM미사용"
                ok = spk.play(key, alog)
                m.update({"답변출처": src, "답변": key, "재생성공": ok})
            m["재생_ms"] = round((time.time() - t_p) * 1000)

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
