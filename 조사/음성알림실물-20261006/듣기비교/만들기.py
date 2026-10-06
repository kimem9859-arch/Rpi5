"""들어 보기용 비교 소리 — ① 지금 파일 ② 같은 문장 느리게 ③ 다듬은 문장 느리게 (사이 0.8초 쉼). 저장소 wav 는 건드리지 않는다."""
import array, os, sys, wave
import sherpa_onnx

D = os.path.expanduser("~/env/tts/vits-mimic3-ko_KO-kss_low")
WAV = "/home/pi/sop-project/Rpi5/Demo/voice/wav"
OUT = sys.argv[1]
SLOW = 0.85
tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(vits=sherpa_onnx.OfflineTtsVitsModelConfig(
        model=f"{D}/ko_KO-kss_low.onnx", tokens=f"{D}/tokens.txt", data_dir=f"{D}/espeak-ng-data"),
        num_threads=2, provider="cpu"), max_num_sentences=1))
SR = tts.sample_rate


def synth(text, speed):
    a = tts.generate(text, sid=0, speed=speed)
    return [int(max(-1, min(1, x)) * 32767) for x in a.samples]


def read(path):
    with wave.open(path) as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
        return list(array.array("h", w.readframes(w.getnframes())))


def write(name, parts):
    gap = [0] * int(SR * 0.8)
    out = []
    for p in parts:
        out += p + gap
    with wave.open(os.path.join(OUT, name), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(array.array("h", out).tobytes())
    print(name, f"{len(out) / SR:.1f}초")


ITEMS = [  # (파일 이름, 지금 wav 키, 지금 문장, 다듬은 문장)
    ("1_비상정지_알림.wav", "alert_emo", "비상정지 중이니 EMO를 복귀한 뒤 차단 해제를 누르세요.",
     "비상정지되었습니다. 비상정지 버튼을 원래대로 돌린 뒤, 차단 해제를 누르세요."),
    ("2_순서경고_B2.wav", "alert_warn_B2", "순서가 다르니 손을 떼고 B2 버튼을 누르세요.",
     "순서가 틀렸습니다. 손을 떼고, B2 버튼을 누르세요."),
    ("3_차단_B2.wav", "alert_block_B2", "차단 중이니 차단 해제를 누른 뒤 B2 버튼부터 다시 누르세요.",
     "차단되었습니다. 차단 해제를 누르고, B2 버튼부터 다시 하세요."),
    ("4_렌치_답.wav", "wrench", "앞에 렌치가 보입니다.", "지금 든 공구는 렌치입니다."),
    ("5_단계아님_답.wav", "notstep", "지금은 공구를 확인하는 단계가 아닙니다.", "지금은 공구 확인 단계가 아닙니다."),
]
for name, key, now_text, new_text in ITEMS:
    write(name, [read(f"{WAV}/{key}.wav"), synth(now_text, SLOW), synth(new_text, SLOW)])
# B2 읽기 — 「B2 버튼」 그대로 · 「비투 버튼」 · 「비 이 버튼」(느리게)
write("6_B2_읽기비교.wav", [synth("B2 버튼을 누르세요.", SLOW), synth("비투 버튼을 누르세요.", SLOW), synth("비 이 버튼을 누르세요.", SLOW)])
