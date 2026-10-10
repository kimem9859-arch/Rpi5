#!/bin/bash
# 측정 진행 도우미 — 노트북 SSH 창에서 띄운다(측정 진행 도우미 설계 2026-10-11 D5).
# 가장 최근 측정 세션을 따라가며 지금 할 줄을 보이고 안경으로 짧은 안내 소리를 낸다 · N = NG · U = 취소 · Q = 끝
cd "$(dirname "$(readlink -f "$0")")" || exit 1
exec python3 measure_guide.py "$@"
