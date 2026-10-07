"""Task 4 — 관문 ② HEF 경로: c001 에서 score_hef_c001 값 = 같은 HEF · 같은 라벨 폴더로 돌린 score_hef.py 출력 · 설계 §4.7.

실행(python3): python3 gate2.py   · 종료 코드 0 = 네 HEF 모두 같음
"""
import re
import subprocess
import sys

import common as C

ROW = re.compile(r"^\s+(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s*$")


def parse(out, names):
    sec = out.split("【운용점")[1].split("【임계값 스윕】")[0]
    got = {}
    for line in sec.splitlines():
        m = ROW.match(line)
        if m and m.group(1) in names:
            got[m.group(1)] = tuple(int(x) for x in m.group(2, 3, 4))
    off = int(re.search(r"클래스 간 오분류 총 (\d+)건", out).group(1))
    return got, off


def main():
    bad = []
    sd = C.set_dir("c001")
    for name, path, g, _pair, _s in C.HEFS:
        names = C.NAMES[g]
        cmd = [sys.executable, str(C.DEMO / "test" / "score_hef.py"), "--labels", str(sd / f"labels_{g}"),
               "--images", str(sd / "orig"), "--hef", str(path), "--names", ",".join(names), "--no-csv"]
        out = subprocess.run(cmd, cwd=C.DEMO, capture_output=True, text=True, check=True, timeout=600).stdout
        theirs, off = parse(out, names)
        ours = C.load_json(C.W / "out" / "hef" / "c001" / f"{name}.json")["요약"]
        mine = {n: (ours["클래스"][n]["tp"], ours["클래스"][n]["fp"], ours["클래스"][n]["fn"]) for n in names}
        same = mine == theirs and ours["오분류"] == off
        print(f"{name}: {'같음 ✅' if same else '다름 ❌'} — 이 스크립트 {mine} 오분류 {ours['오분류']} ↔ score_hef {theirs} 오분류 {off}")
        if not same:
            bad.append(name)
    print("관문 ② " + ("✅" if not bad else "❌ " + " · ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
