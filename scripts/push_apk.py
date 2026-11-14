#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Push MyDvResume.apk to the TCL TV via 多屏互动 (tcast, TCP 6553).

Starts a local HTTP server for the TV to download the APK, sets up adb reverse,
then speaks the tcast INSTALL protocol. The TV shows a prompt; the user must
choose 同意 (press Right once, then OK).

Prints a state log; exits 0 when the TV reports the app installed.
"""
import hashlib
import os
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

TV = "192.168.1.26"
TCAST_PORT = 6553
HTTP_PORT = 8765
PKG = "com.wb.mydvresume"
LABEL = "myDV Resume"
VERSION = "16"
APK_NAME = "MyDvResume.apk"
APK_DIR = r"C:\Temp\wbapk"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
TIMEOUT = 300


def adb(*args):
    p = subprocess.run([ADB] + list(args), capture_output=True, timeout=30)
    return (p.stdout + p.stderr).decode("utf-8", "replace").strip()


def local_ip():
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect((TV, 5555))
        return s.getsockname()[0]
    finally:
        s.close()


def send(sock, text):
    data = text.encode()
    sock.sendall(struct.pack(">i", len(data)) + data)


def messages(buf):
    out = []
    while len(buf) >= 4:
        n = struct.unpack(">i", buf[:4])[0]
        if n < 0:
            raise ValueError("negative length")
        if len(buf) < 4 + n:
            break
        out.append(buf[4:4 + n].decode("utf-8", "replace"))
        buf = buf[4 + n:]
    return out, buf


def main():
    apk = os.path.join(APK_DIR, APK_NAME)
    if not os.path.isfile(apk):
        print("APK missing:", apk, flush=True)
        return 1
    print("APK: %s (%d bytes)" % (apk, os.path.getsize(apk)), flush=True)

    os.chdir(APK_DIR)
    handler = SimpleHTTPRequestHandler
    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print("HTTP server on 0.0.0.0:%d" % HTTP_PORT, flush=True)

    ip = local_ip()
    print("PC LAN IP:", ip, flush=True)
    print("adb connect:", adb("connect", TV + ":5555").splitlines()[-1], flush=True)
    print("adb reverse:", adb("reverse", "tcp:%d" % HTTP_PORT, "tcp:%d" % HTTP_PORT) or "(ok)", flush=True)

    urls = [
        "http://127.0.0.1:%d/%s" % (HTTP_PORT, APK_NAME),   # via adb reverse
        "http://%s:%d/%s" % (ip, HTTP_PORT, APK_NAME),       # direct LAN fallback
    ]
    attempt = 0
    start = time.monotonic()
    deadline = start + TIMEOUT

    while time.monotonic() < deadline and attempt < len(urls):
        url = urls[attempt]
        attempt += 1
        print("=== attempt %d: %s ===" % (attempt, url), flush=True)
        try:
            sock = socket.create_connection((TV, TCAST_PORT), timeout=5)
        except Exception as e:
            print("  connect failed:", e, flush=True)
            continue
        sock.settimeout(1)
        send(sock, "159>>1>>0")
        path_md5 = hashlib.md5(url.encode()).hexdigest()
        send(sock, ">>".join(["223", "INSTALL", PKG, LABEL, url, "2", VERSION,
                              "1", "", "", "", path_md5]))
        print("  INSTALL request sent; waiting for 同意 on the TV...", flush=True)

        buf = b""
        last_beat = time.monotonic()
        try:
            while time.monotonic() < deadline:
                try:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                except socket.timeout:
                    pass
                found, buf = messages(buf)
                for msg in found:
                    parts = msg.split(">>")
                    if len(parts) < 5 or parts[0] != "223" or parts[2] != PKG:
                        continue
                    if parts[1] == "INSTALL":
                        st = parts[4]
                        print("  INSTALL state:", st, flush=True)
                        if st == "confirm_pending":
                            print("  >>> 请在电视上按「右」选中「同意」再按确认 <<<", flush=True)
                        elif st == "denied":
                            print("  用户在电视上拒绝了", flush=True)
                            sock.close()
                            return 1
                        elif st == "installed":
                            print("  INSTALLED", flush=True)
                            sock.close()
                            httpd.shutdown()
                            return 0
                    elif parts[1] == "PROGRESS":
                        stage, pct = parts[4], parts[5] if len(parts) > 5 else "?"
                        print("  PROGRESS stage=%s percent=%s" % (stage, pct), flush=True)
                        if stage == "5":
                            print("  INSTALLED", flush=True)
                            sock.close()
                            httpd.shutdown()
                            return 0
                        if stage == "2":
                            print("  下载/安装失败，尝试下一个 URL", flush=True)
                            break
                        if stage == "4":
                            print("  TCL 验证器拒绝了该 APK（通常是声明了 HOME）", flush=True)
                            sock.close()
                            httpd.shutdown()
                            return 1
                if time.monotonic() - last_beat > 5:
                    send(sock, "150>>")
                    last_beat = time.monotonic()
        finally:
            try:
                sock.close()
            except Exception:
                pass
        print("  attempt %d ended" % attempt, flush=True)

    httpd.shutdown()
    print("TIMEOUT / no install reported", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
