import socket, sys, time
s = socket.create_connection((sys.argv[1], 8889)); f = open(sys.argv[2], "a")
t0 = t = time.time(); n = 0
while True:
    d = s.recv(8192)
    if not d:
        f.write("끊김\n"); break
    n += len(d)
    if time.time() - t >= 10:
        now = time.time(); r = n / (now - t)
        f.write(f"{now - t0:6.0f}s {r:8.0f} B/s {r / 32000 * 100:5.1f}%\n"); f.flush(); t, n = now, 0
