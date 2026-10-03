"""ssh ProxyCommand 용 중계 — 연결할 때 TCP 최대 조각(MSS)을 작게 알려 상대가 작은 조각으로만 보내게 한다.

데스크톱 WSL → 파이 방향에서 약 1,100바이트 이상 조각이 길에서 버려지는 문제(2026-10-03 시험) 우회용. 시스템 설정은 바꾸지 않는다.
사용: ssh -o ProxyCommand='python3 mss_proxy.py %h %p' wsl-train ...
"""
import os
import selectors
import socket
import sys

MSS = 900

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, MSS)
s.connect((sys.argv[1], int(sys.argv[2])))
sel = selectors.DefaultSelector()
sel.register(sys.stdin.fileno(), selectors.EVENT_READ, "in")
sel.register(s, selectors.EVENT_READ, "sock")
while True:
    for key, _ in sel.select():
        if key.data == "in":
            data = os.read(sys.stdin.fileno(), 65536)
            if not data:
                s.shutdown(socket.SHUT_WR)
                sel.unregister(sys.stdin.fileno())
                continue
            s.sendall(data)
        else:
            data = s.recv(65536)
            if not data:
                sys.exit(0)
            os.write(sys.stdout.fileno(), data)
