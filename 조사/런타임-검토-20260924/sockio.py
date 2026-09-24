import socket, threading, time
a, b = socket.socketpair()
f = a.makefile("rb")
a.settimeout(0.3)
def later():
    time.sleep(0.6); b.sendall("[재생 완료]\n".encode())
threading.Thread(target=later).start()
out=[]
end=time.time()+2
while time.time()<end:
    try:
        line=f.readline()
    except socket.timeout:
        out.append("timeout"); continue
    except OSError as e:
        out.append(f"OSError:{e}"); break
    out.append(line.decode()); break
print(out)
