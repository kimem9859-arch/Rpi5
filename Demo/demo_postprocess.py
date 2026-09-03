"""시연영상 촬영 — 촬영이 끝난 뒤 규격을 맞춘다.

    python3 demo_postprocess.py <세트폴더>

설계 = 상위 `docs/superpowers/specs/2026-09-03-시연영상-촬영-design.md`

🔴 **왜 촬영 중에 안 하고 여기서 하나.** 2026-09-03 실측에서 1080p 인코딩 5벌이
   4코어를 250% 넘게 먹어 GUI 가 FPS 0.6 까지 떨어졌다. 사람이 연기하는 동안에는
   **원본 그대로만 담고**, 아래 두 가지는 GUI 가 닫힌 뒤에 한다. 결과 파일은 같다.

하는 일:
  ③ 1인칭 두 벌 = 원본(480×640)을 규격 캔버스에 레터박스로 얹기

🔴 ②GUI화면만은 여기서 못 만든다 — 이 UI 는 모든 UI 가 영상 위에 떠 있는 글라스
   구조라 영상 영역을 덧칠하면 UI 까지 지워진다. ②는 「UI만」 회차에서 직접 찍는다.
"""
import json
import os
import subprocess
import sys

_X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]


def _run(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])


def _find(folder, needle):
    for name in sorted(os.listdir(folder)):
        if needle in name and name.endswith('.mp4'):
            return os.path.join(folder, name)
    return None


def process(folder):
    meta_path = os.path.join(folder, '촬영메타.json')
    if not os.path.exists(meta_path):
        print(f"❌ 촬영메타.json 이 없습니다 — {folder}")
        return 1
    with open(meta_path) as fp:
        meta = json.load(fp)
    tw, th = meta['target']

    done = []

    # 🔴 ②GUI화면만을 ①에서 파생하지 않는다 — 이 UI 는 모든 UI 가 영상 위에 떠 있는
    #    글라스 구조라, 영상 영역을 덧칠하면 UI 까지 지워진다(2026-09-03 실측).
    #    ②는 SOP_DEMO_HIDE_VIDEO=1 회차에서 GUI 가 직접 검정 배경으로 그려 얻는다.

    # ③ 1인칭 두 벌 — 레터박스로 규격 맞추기
    vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
          f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black")
    for tag in ('1인칭풀_오버레이켬', '1인칭풀_오버레이끔'):
        src = _find(folder, tag)
        if not src:
            print(f"  ⚠️ {tag} 파일이 없습니다")
            continue
        tmp = src + '.tmp.mp4'
        print(f"  ▪ {tag} 규격 맞추는 중...")
        _run(["-i", src, "-vf", vf] + _X264 + [tmp])
        os.replace(tmp, src)
        done.append(src)

    print(f"  ✅ 마무리 완료 — {len(done)}개 파일")
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(process(sys.argv[1]))
