#!/usr/bin/env python3

# Allow another docker container to run commands on this container
# This is the script to run on the server container.
# The client can connect and run a command like so:
#    $ echo whoami | nc servercontainername 2222
#    root

import socket
import subprocess as sp
from datetime import datetime

LISTEN_PORT = 2222

s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s1.bind(("0.0.0.0", LISTEN_PORT))
s1.listen(1)
print("Listening for shell commands on 0.0.0.0:2222", flush=True)

conn, addr = s1.accept()
while True:
    cmd = conn.recv(1024).decode()
    if not cmd:
        conn, addr = s1.accept()
        continue

    timestamp = datetime.now().isoformat()
    client_ip, client_port = conn.getsockname()
    print(f'\n[{timestamp}][{client_ip}:{client_port}] $', cmd)

    with sp.Popen(cmd, shell=True, stdout=sp.PIPE, stderr=sp.STDOUT, stdin=sp.PIPE, bufsize=1, universal_newlines=True) as p:
        for line in p.stdout:
            print(line.strip(), flush=True)
            conn.sendall(line.encode("utf-8"))

    conn.close()
    conn, addr = s1.accept()
