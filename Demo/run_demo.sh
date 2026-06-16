#!/usr/bin/env bash
# SOP 가디언 Demo 실행 런처 (바탕화면 바로가기용)
# main.py 는 같은 폴더의 모듈을 상대 import 하므로 반드시 Demo 디렉터리에서 실행한다.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

echo "=== SOP 가디언 Demo 실행 ==="
echo "경로: $(pwd)"
echo

python3 main.py
status=$?

echo
echo "=== 종료 (exit code: $status) ==="
echo "창을 닫으려면 Enter 를 누르세요."
read -r _
