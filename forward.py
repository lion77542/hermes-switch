#!/usr/bin/env python3
"""Simple port forward: external -> localhost"""
import socket, threading, sys, os
sys.dont_write_bytecode = True

LHOST = '192.168.1.89'
LPORT = 6186
RHOST = '127.0.0.1'
RPORT = 6185

def forward(src, dst):
    try:
        while True:
            d = src.recv(4096)
            if not d: break
            dst.sendall(d)
    except: pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

def handle(conn):
    try:
        target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        target.connect((RHOST, RPORT))
        threading.Thread(target=forward, args=(conn, target), daemon=True).start()
        threading.Thread(target=forward, args=(target, conn), daemon=True).start()
    except Exception as e:
        print(f"Error: {e}")

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind((LHOST, LPORT))
    s.listen(10)
    print(f"Forwarding {LHOST}:{LPORT} -> {RHOST}:{RPORT}")
    while True:
        conn, addr = s.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()
except KeyboardInterrupt:
    print("stopped")
except Exception as e:
    print(f"Failed: {e}")
    sys.exit(1)
