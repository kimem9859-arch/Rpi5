"""가짜 인터락 아두이노 — 가상 시리얼(pty)로 명령 한 줄(RUN · WARN · BLOCK)을 받아 「ACK」 로 답한다.

설계 = 상위 sop-project docs/superpowers/specs/2026-10-12-학교방문준비-design.md §7.1 · 규약 = interlock.py 머리말(명령 + \\n → ACK)
쓰는 법: fi = FakeInterlock(on_cmd=…).start() → SOP_INTERLOCK_PORT=fi.port 로 시연 · 램프 도구를 붙인다.
"""
import os
import pty
import threading
import time
import tty


class FakeInterlock:
    def __init__(self, on_cmd=None, ack=True):
        self.on_cmd = on_cmd or (lambda cmd, t: None)
        self.ack = ack
        self.cmds = []
        self._master, self._slave = pty.openpty()
        tty.setraw(self._slave)                  # 줄 바꿈 변환 없이(아두이노 시리얼처럼)
        self.port = os.ttyname(self._slave)      # 🔑 slave 를 열어 둔다 — 닫으면 상대가 열기 전에 사라진다
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        for fd in (self._master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def _loop(self):
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = os.read(self._master, 256)
            except OSError:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.strip().decode("ascii", "replace")
                if not cmd:
                    continue
                t = time.monotonic()
                self.cmds.append((t, cmd))
                self.on_cmd(cmd, t)
                if self.ack:
                    try:
                        os.write(self._master, b"ACK\n")
                    except OSError:
                        return
