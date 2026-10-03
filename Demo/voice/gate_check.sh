#!/bin/bash
# 음성비서 촬영 직전 관문 러너 — 손으로 하던 확인을 한 번에 돈다.
#
# 실행: ./Demo/voice/gate_check.sh
#
# 🔴 HW 가 필요하다. 다른 세션이 ESP32 를 쓰는 중이면 돌리지 말 것 — 측정이 섞인다.
# 🔴 음성비서가 돌고 있으면 시작하지 않는다 — 8889·8890 을 빼앗고, 업링크를 못 붙어 거짓 통과한다
#    (R2 M10 · 설계 2026-10-03 §4.9). 시연 프로그램을 끄거나 SOP_VOICE=0 으로 띄운다.
#
# 무엇을 보나 (Demo/voice/시연절차.md §3):
#   G0  주소·도달성   — .camera_ip(보드는 하나다)
#   G2  무선 오디오 왕복 — 1kHz 순음 전송 후 체크섬 일치
#   G3  업링크 중 FPS  — 마이크를 빨아들이는 동안 카메라가 15fps 이상인가
#   ⛔  명료도        — 답변 4개를 재생만 한다. **판정은 사람 귀다**(귀 옆 5cm)
#
# 🔑 판정이 사람에게 달린 것은 자동화하지 않는다 — 재생까지만 하고 묻는다.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."     # → Rpi5
PY="$HOME/env/tts/.venv/bin/python"
CAM_IP_FILE=Demo/.camera_ip
LOCK="${SOP_VOICE_LOCK:-/tmp/sop_voice_assistant.lock}"
FAILS=0

if ! flock -n "$LOCK" true 2>/dev/null; then
    echo "🔴 음성비서가 돌고 있다($LOCK) — 마이크(8889)·명령 채널(8890)을 빼앗고 측정이 섞인다. 끄고 다시 돌려라."
    exit 1
fi

ok()   { echo "  ✅ $1"; }
bad()  { echo "  ❌ $1"; FAILS=$((FAILS+1)); }
head_() { echo; echo "── $1"; }

head_ "G0 · 주소와 도달성"
CAM=$(cat "$CAM_IP_FILE" 2>/dev/null || true)
[ -n "$CAM" ] && ok "보드 $CAM" || { bad "$CAM_IP_FILE 가 비었다"; exit 1; }
ping -c2 -W2 "$CAM" >/dev/null 2>&1 && ok "보드 ping" || bad "보드 무응답"

head_ "G2 · 무선 오디오 왕복 (체크섬)"
TONE=/tmp/gate_tone.wav
[ -f "$TONE" ] || $PY arduino/mic_speaker_test/esp32_audio.py tone 1000 2 "$TONE" >/dev/null 2>&1
OUT=$($PY arduino/mic_speaker_test/esp32_audio.py --tcp "$CAM:8890" play "$TONE" 2>&1 || true)
echo "$OUT" | grep -q "ok" && ok "체크섬 일치 — 「삐—」 가 들렸는가?" \
                           || { bad "체크섬 불일치/전송 실패"; echo "$OUT" | tail -3 | sed 's/^/     /'; }

head_ "G3 · 마이크 업링크 중 카메라 FPS (합격선 ≥15)"
$PY - "$CAM" <<'PYEOF'
import socket, struct, sys, threading, time
ip = sys.argv[1]
stop = False
up = [False]
def drain():
    try:
        m = socket.create_connection((ip, 8889), 5); m.settimeout(5)
        up[0] = True
        while not stop:
            if not m.recv(8192): break
        m.close()
    except OSError as e:
        print(f"  ⚠️ 업링크 연결 실패: {e}")
threading.Thread(target=drain, daemon=True).start()
time.sleep(1)
try:
    c = socket.socket(); c.settimeout(8); c.connect((ip, 8888))
except OSError as e:
    print(f"  ❌ 카메라 연결 실패: {e}"); sys.exit(1)
t0 = time.time(); n = 0
while time.time() - t0 < 30:
    h = c.recv(4)
    if len(h) < 4: break
    ln = struct.unpack('<I', h)[0]; got = 0
    while got < ln:
        b = c.recv(min(8192, ln - got))
        if not b: break
        got += len(b)
    n += 1
stop = True; c.close()
fps = n / 30
if not up[0]:
    # 🔴 업링크 없이 잰 FPS 는 이 관문의 질문(「마이크를 빨아들이는 동안」)에 답하지 않는다 — 거짓 통과(R2 M10)
    print(f"  ❌ 업링크에 못 붙었다 — {fps:.1f} fps 는 마이크 없이 잰 값이라 판정하지 않는다")
    sys.exit(2)
print(f"  {'✅' if fps >= 15 else '❌'} 업링크 중 {fps:.1f} fps ({n} 프레임 / 30초)")
sys.exit(0 if fps >= 15 else 1)
PYEOF
[ $? -eq 0 ] && ok "NFR-1 충족" || bad "🔴 15fps 미만이거나 업링크 없이 잰 값 — 촬영 전에 손봐야 한다"

head_ "⛔ 명료도 — 재생만 한다. 판정은 사람이 한다"
echo "  🔴 스피커를 **귀 옆 5cm** 에 두고 들으세요(§10.49 가 정한 조건)."
for k in checking wrench none notstep; do
  echo "     ▶ $k"
  $PY arduino/mic_speaker_test/esp32_audio.py --tcp "$CAM:8890" \
      play "Demo/voice/wav/$k.wav" >/dev/null 2>&1 || echo "     ❌ 재생 실패"
  sleep 1
done
echo "  ❓ 네 문장이 **무슨 말인지 알아들렸는가?**"
echo "     아니면 → Demo/voice/make_answers.py 의 문장을 줄여 다시 합성한다(2분)."

head_ "요약"
if [ $FAILS -eq 0 ]; then
  echo "  ✅ 기계가 볼 수 있는 관문은 전부 통과. 남은 것은 명료도(사람 귀)뿐이다."
else
  echo "  ❌ 실패 $FAILS 건 — Demo/voice/시연절차.md §4 증상별 대응표를 보라."
fi
exit $FAILS
