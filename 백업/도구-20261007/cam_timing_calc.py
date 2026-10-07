#!/usr/bin/env python3
"""OV3660 + esp32-camera 클럭·프레임률 탐색기 (실HW 불필요)

🔑 왜 있나 — 2026-09-22, 27.8fps 상한의 기전을 규명하며 만들었다. 상한은 ESP32 도
   Wi-Fi 도 아니고 **센서가 한 장을 읽어내는 시간**이 정한 값이다:

       fps = SCLK / (HTS × VTS)

   이 계산기는 그 식에 드라이버의 PLL 계산을 그대로 얹어, 설정을 바꿨을 때
   나올 fps 를 **카메라 없이** 구한다. 카메라가 죽어 있어도(2026-09-22 실제로
   그랬다) 설계 판단을 진행하기 위한 도구다.

🔴 **여기 수치를 적지 않는다** — 산출 수치의 정본은 통합문서 §12 `[CURRENT]` 표다.

📚 1차 출처 (이 파일은 아래를 옮긴 것이고, 스스로 만든 값이 없다)
   · PLL 계산식·해상도 분기 = espressif/esp32-camera `sensors/ov3660.c`
     (calc_sysclk / set_framesize · master · 2026-09-22 조회)
   · HTS·VTS 표         = 같은 저장소 `sensors/private_include/ov3660_settings.h`
                           (ratio_table · 4x3 = total 2300 × 1564)
   · ESP32-S3 XCLK 생성 = 같은 저장소 `target/esp32s3/ll_cam.c`
                           (`cam_clkm_div_num = 160000000 / xclk_freq_hz`)
   · 센서 전기 규격     = OV3660_CSP3_DS_1.3 §2.9.1 · 표 2-2
                           (입력 6~27MHz · REFIN 4~13.5MHz · VCO 150~500MHz
                            · 정식 동작 system clock 27MHz(VGA/QVGA)·54MHz(그 외))

⚠️ **계산이지 측정이 아니다.** 이 도구가 말할 수 있는 것은 「센서가 프레임을
   내보내는 속도」뿐이다. 실제로 파이에 도착하는 FPS 는 JPEG 압축·전송이 더
   깎는다(§12.64: 화질을 올리면 프레임이 커져 순간 끊김이 58배가 됐다).
   그래서 산출값은 **상한**이며, 실HW 측정 없이 §12 에 확정값으로 올리지 않는다.

사용법:
    python3 cam_timing_calc.py --verify     # 자체 검증(먼저 이것부터)
    python3 cam_timing_calc.py              # 규격 내 조합 탐색
    python3 cam_timing_calc.py --all        # 규격 초과 조합까지
"""
import argparse
import sys

# ── 드라이버 원문 상수 (ov3660.c) ────────────────────────────────────────────
PLL_PRE_DIV2X_MAP = [2, 3, 4, 6]   # 값을 2배로 둬 실수 연산을 피한다(원문 주석)
PLL_SELD52X_MAP   = [2, 2, 4, 5]

# ── 데이터시트 규격 (OV3660_CSP3_DS_1.3 §2.9.1) ──────────────────────────────
XCLK_MIN_HZ, XCLK_MAX_HZ = 6_000_000, 27_000_000
REFIN_MIN_HZ, REFIN_MAX_HZ = 4_000_000, 13_500_000
VCO_MIN_HZ, VCO_MAX_HZ = 150_000_000, 500_000_000
SCLK_SPEC_MAX_HZ = 54_000_000      # 표 2-2 의 정식 동작 클럭 최대

# ── 현행 펌웨어 설정 (Rpi5/arduino/camera_stream_tcp/camera_stream_tcp.ino) ──
CUR_XCLK_HZ = 20_000_000
CUR_PLL = dict(bypass=False, multiplier=30, sys_div=1, pre_div=3,
               root_2x=False, seld5=0, pclk_manual=True, pclk_div=10)

# ── 4:3 화면의 HTS·VTS (ov3660_settings.h · ratio_table[0]) ──────────────────
TOTAL_X_4X3 = 2300
TOTAL_Y_4X3 = 1564
# 2x2 binning 이 걸리면 드라이버가 세로를 이렇게 줄인다 (ov3660.c set_framesize)
TOTAL_Y_BINNED = TOTAL_Y_4X3 // 2 + 1        # = 783
# binning 시 실제로 읽어내는 줄 수 — VTS 는 이보다 작을 수 없다
READOUT_ROWS_BINNED = (1547 - 0 + 1) // 2    # = 774 (start_y=0, end_y=1547)


def calc_clocks(xclk_hz, bypass, multiplier, sys_div, pre_div, root_2x, seld5,
                pclk_manual, pclk_div):
    """ov3660.c 의 calc_sysclk() 를 그대로 옮긴 것. 반환 = (VCO, PLLCLK, SYSCLK, PCLK).

    🔴 재구현이 아니라 이식이다 — 식을 고치지 말 것. 드라이버가 바뀌면 여기도 바꾼다.
    """
    if not sys_div:
        sys_div = 1
    pre_div2x = PLL_PRE_DIV2X_MAP[pre_div]
    root_div = 2 if root_2x else 1
    seld52x = PLL_SELD52X_MAP[seld5]

    vco = (xclk_hz // 1000) * multiplier * root_div * 2 // pre_div2x   # kHz
    pllclk = xclk_hz if bypass else (vco * 1000 * 2 // sys_div // seld52x)
    pclk = pllclk // 2 // (pclk_div if (pclk_manual and pclk_div) else 1)
    sysclk = pllclk // 4
    return vco * 1000, pllclk, sysclk, pclk


def fps_of(sclk_hz, hts, vts):
    """fps = SCLK / (HTS × VTS) — 데이터시트 §3.4.4 예시로 검증된 식."""
    return sclk_hz / (hts * vts)


def esp32s3_xclk_options():
    """ESP32-S3 가 실제로 만들 수 있는 XCLK — 160MHz 의 정수 분주뿐이다.

    출처 = target/esp32s3/ll_cam.c `cam_clkm_div_num = 160000000 / xclk_freq_hz`
    (정수 나눗셈이라, 나누어떨어지지 않는 주파수를 넣으면 조용히 다른 값이 된다.)
    """
    out = []
    for div in range(6, 28):
        hz = 160_000_000 // div
        if XCLK_MIN_HZ <= hz <= XCLK_MAX_HZ:
            out.append((hz, div))
    return out


def check_spec(xclk_hz, pre_div, vco_hz, sclk_hz):
    """데이터시트 규격 위반 목록을 돌려준다. 빈 리스트 = 규격 내."""
    bad = []
    if not (XCLK_MIN_HZ <= xclk_hz <= XCLK_MAX_HZ):
        bad.append(f"입력클럭 {xclk_hz/1e6:.2f}MHz(규격 6~27)")
    refin = xclk_hz / (PLL_PRE_DIV2X_MAP[pre_div] / 2)
    if not (REFIN_MIN_HZ <= refin <= REFIN_MAX_HZ):
        bad.append(f"REFIN {refin/1e6:.2f}MHz(규격 4~13.5)")
    if not (VCO_MIN_HZ <= vco_hz <= VCO_MAX_HZ):
        bad.append(f"VCO {vco_hz/1e6:.0f}MHz(규격 150~500)")
    if sclk_hz > SCLK_SPEC_MAX_HZ:
        bad.append(f"SCLK {sclk_hz/1e6:.1f}MHz(정식 최대 54)")
    return bad


# ═══════════════════════════════════════════════════════════════════════════
#  자체 검증 — 이 도구를 믿어도 되는지 먼저 증명한다
# ═══════════════════════════════════════════════════════════════════════════
def verify():
    """알려진 3개 지점을 재현한다. 하나라도 어긋나면 산출값을 쓰지 않는다."""
    ok = True

    def check(name, got, want, tol, unit=""):
        nonlocal ok
        good = abs(got - want) <= tol
        ok &= good
        mark = "✅" if good else "❌"
        print(f"  {mark} {name}\n       계산 {got:.2f}{unit} · 기대 {want:.2f}{unit} (허용 ±{tol}{unit})")

    print("자체 검증 — 출처가 아는 값을 이 코드가 재현하는가\n")

    # (1) 데이터시트 §3.4.4 예시: full resolution 2048x1536 을 15fps 로 낼 때
    #     row_per_frame(VTS) = 1564. 그리고 표 2-8 이 그때의 pixel clock 을
    #     54MHz 라고 적었다. 두 값이 같은 식에서 나와야 한다.
    check("데이터시트 §3.4.4 예시 (54MHz · 2300×1564)",
          fps_of(54_000_000, TOTAL_X_4X3, TOTAL_Y_4X3), 15.0, 0.05, "fps")

    # (2) 드라이버 PLL 계산 — ov3660.c 주석이 "50MHz SYSCLK and 10MHz PCLK" 라고
    #     적어 둔 분기를 그대로 넣어 그 숫자가 나오는지 본다.
    vco, pllclk, sclk, pclk = calc_clocks(CUR_XCLK_HZ, **CUR_PLL)
    check("드라이버 JPEG 분기 SYSCLK (주석: 50MHz)", sclk / 1e6, 50.0, 0.1, "MHz")
    check("드라이버 JPEG 분기 PCLK (주석: 10MHz)", pclk / 1e6, 10.0, 0.1, "MHz")

    # (3) 현행 펌웨어 실측과의 대조 — §12.64 의 VGA q15 3회 평균 27.04fps,
    #     저장 없는 회차 27.7fps. 계산은 그 사이에 들어와야 한다.
    cur = fps_of(sclk, TOTAL_X_4X3, TOTAL_Y_BINNED)
    check("현행 설정 fps (실측 27.0~27.8)", cur, 27.4, 0.5, "fps")

    print()
    if ok:
        print("✅ 3개 지점 모두 재현 — 이 계산을 설계 판단에 쓸 수 있다.")
        print("   ⚠️ 단, 산출값은 '센서가 내보내는 상한'이고 실제 도착 FPS 는 더 낮다.")
    else:
        print("❌ 검증 실패 — 산출값을 쓰지 말 것. 드라이버나 출처가 바뀌었는지 확인한다.")
    return ok


# ═══════════════════════════════════════════════════════════════════════════
#  탐색
# ═══════════════════════════════════════════════════════════════════════════
def search(include_out_of_spec=False):
    _, _, cur_sclk, _ = calc_clocks(CUR_XCLK_HZ, **CUR_PLL)
    cur_fps = fps_of(cur_sclk, TOTAL_X_4X3, TOTAL_Y_BINNED)

    print(f"현행 = XCLK {CUR_XCLK_HZ/1e6:.0f}MHz · SCLK {cur_sclk/1e6:.0f}MHz "
          f"· HTS×VTS {TOTAL_X_4X3}×{TOTAL_Y_BINNED} → {cur_fps:.2f} fps\n")

    seen = {}
    for xclk_hz, _div in esp32s3_xclk_options():
        for multiplier in range(1, 32):
            for sys_div in range(1, 16):
                for pre_div in range(4):
                    for root_2x in (False, True):
                        for seld5 in range(4):
                            vco, _pll, sclk, pclk = calc_clocks(
                                xclk_hz, False, multiplier, sys_div, pre_div,
                                root_2x, seld5, True, CUR_PLL["pclk_div"])
                            bad = check_spec(xclk_hz, pre_div, vco, sclk)
                            if bad and not include_out_of_spec:
                                continue
                            if sclk <= cur_sclk:
                                continue
                            fps = fps_of(sclk, TOTAL_X_4X3, TOTAL_Y_BINNED)
                            key = round(sclk / 1e5)
                            cand = (fps, sclk, xclk_hz, multiplier, sys_div,
                                    pre_div, root_2x, seld5, pclk, bad)
                            # 같은 SCLK 면 규격 위반이 적은 쪽을 남긴다
                            if key not in seen or len(bad) < len(seen[key][9]):
                                seen[key] = cand

    rows = sorted(seen.values(), key=lambda r: -r[0])
    if not rows:
        print("현행보다 빠르면서 규격을 지키는 조합이 없다.")
        return

    print(f"{'fps':>7} {'증가':>7}  {'SCLK':>8} {'XCLK':>8}  mul sys pre root seld5  {'PCLK':>7}  규격")
    print("─" * 96)
    for fps, sclk, xclk, mul, sys_d, pre, root, seld5, pclk, bad in rows[:15]:
        flag = "✅ 내" if not bad else "⚠️ " + "; ".join(bad)
        print(f"{fps:7.2f} {fps/cur_fps-1:+6.1%}  {sclk/1e6:7.1f}M {xclk/1e6:7.2f}M "
              f"{mul:4d}{sys_d:4d}{pre:4d}{str(root):>6}{seld5:6d}  {pclk/1e6:6.1f}M  {flag}")

    print()
    inspec = [r for r in rows if not r[9]]
    if inspec:
        best = inspec[0]
        print(f"🔑 규격 내 최선 = {best[0]:.2f} fps (현행 대비 {best[0]/cur_fps-1:+.1%})")
        print(f"   XCLK {best[2]/1e6:.2f}MHz · multiplier {best[3]} · sys_div {best[4]} "
              f"· pre_div {best[5]} · root_2x {best[6]} · seld5 {best[7]}")
    print()
    print("🔴 센서의 정식 고속 모드(표 2-2 의 XGA 45fps·VGA 60fps)는 이 표에 없다 —")
    print("   그 모드들은 binning 이 아니라 subsampling 을 쓰고 HTS·VTS 가 통째로")
    print("   다른 레지스터 세트다. esp32-camera 드라이버는 그 세트를 갖고 있지 않다.")
    print(f"   참고로 VTS 는 {READOUT_ROWS_BINNED} 줄 밑으로 못 내린다(실제로 읽는 줄 수) —")
    print(f"   지금 {TOTAL_Y_BINNED} 이라 세로 여백을 줄여 얻을 수 있는 것은 "
          f"최대 {TOTAL_Y_BINNED/READOUT_ROWS_BINNED-1:+.1%} 뿐이다.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="자체 검증만 수행")
    ap.add_argument("--all", action="store_true", help="규격 초과 조합도 표시")
    args = ap.parse_args()

    if args.verify:
        sys.exit(0 if verify() else 1)

    if not verify():
        print("\n🔴 검증이 실패해 탐색을 중단한다.")
        sys.exit(1)
    print("\n" + "═" * 96 + "\n")
    search(include_out_of_spec=args.all)


if __name__ == "__main__":
    main()
