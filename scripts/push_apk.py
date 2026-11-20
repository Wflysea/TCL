#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Push MyDvResume.apk to the TCL TV via 多屏互动 (tcast, TCP 6553).

Starts a local HTTP server for the TV to download the APK, sets up adb reverse,
then speaks the tcast INSTALL protocol. The TV shows a prompt; the user must
choose 同意 (press Right once, then OK).

Version visibility (v4.4, 2026-11-20): the TCL 多屏互动 confirm dialog is
HARDCODED (only tv_title="多屏互动", a fixed tv_content sentence, two buttons
and an icon) and renders NO app name / version. v4.3 added an on-TV overlay
banner, but the user asked to remove it, so v4.4 keeps version info ONLY on
this PC console:

  - console banner BEFORE pushing (local APK version, sha256, size, TV
    installed version) and a VERSION CHECK after installation.

The on-TV TYPE_ACCESSIBILITY_OVERLAY banner and its PUSH_BANNER broadcast were
REMOVED from both this script and ResumeService in v4.4.

versionCode / versionName are read straight from the APK (aapt2 badging, with
AndroidManifest.xml as fallback); no hardcoded VERSION constant, so the pushed
version can never drift from the built APK.

Usage:
    python push_apk.py                  # push; console shows version
    python push_apk.py --info-only      # just print local + TV versions, no push
    python push_apk.py --plain-label    # keep the bare app name in the protocol

Prints a state log; exits 0 when the TV reports the app installed.
"""
import argparse
import atexit
import hashlib
import os
import re
import shutil
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
LABEL_BASE = "myDV Resume"
# Display-only: maps versionCode -> release tag used in the changelog. Not used
# for any protocol field; unknown codes simply omit the tag.
RELEASE_NAMES = {17: "v4.1", 18: "v4.2", 19: "v4.2.1", 20: "v4.3", 21: "v4.4"}
APK_NAME = "MyDvResume.apk"
APK_DIR = r"C:\Temp\wbapk"
AAPT2 = os.path.join(APK_DIR, "tools", "aapt2.exe")
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
TIMEOUT = 300
# After the TV reports "installed", keep the tcast session (and the APK HTTP
# server) alive briefly. Closing the socket immediately makes the TV log
# "Session ... close isRemove:true" + "onSessionDisconnect", then broadcast
# status 1 to the launcher, which flashes a spurious "download failed" toast
# even though PACKAGE_ADDED was already sent and the APK is installed.
# Evidence (2026-11-15 19:22:25): PACKAGE_ADDED -> close/sessionDisconnect
# -> "Send broadcast status 1 to launcher" within 40 ms.
GRACE_SECONDS = 10


def adb(*args):
    p = subprocess.run([ADB] + list(args), capture_output=True, timeout=30)
    return (p.stdout + p.stderr).decode("utf-8", "replace").strip()


def apk_version(apk):
    """(versionCode, versionName) read from the signed APK, else the manifest."""
    vc, vn = "", ""
    if os.path.isfile(AAPT2):
        try:
            p = subprocess.run([AAPT2, "dump", "badging", apk],
                               capture_output=True, timeout=30)
            head = (p.stdout + p.stderr).decode("utf-8", "replace")[:3000]
            m = re.search(r"versionCode='(\d+)'", head)
            if m:
                vc = m.group(1)
            m = re.search(r"versionName='([^']*)'", head)
            if m:
                vn = m.group(1)
        except (OSError, subprocess.SubprocessError) as e:
            print("  (aapt2 unavailable: %s; falling back to manifest)" % e,
                  flush=True)
    if not vc or not vn:
        manifest = os.path.join(APK_DIR, "AndroidManifest.xml")
        try:
            txt = open(manifest, encoding="utf-8", errors="replace").read()
            if not vc:
                m = re.search(r'android:versionCode="(\d+)"', txt)
                vc = m.group(1) if m else ""
            if not vn:
                m = re.search(r'android:versionName="([^"]*)"', txt)
                vn = m.group(1) if m else ""
        except OSError:
            pass
    return vc or "?", vn or "?"


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def device_version():
    """Version currently installed on the TV, as (versionCode, versionName)."""
    # adb daemon restarts between terminal calls on this PC, so always connect
    # in the same helper before querying.
    adb("connect", TV + ":5555")
    out = adb("-s", TV + ":5555", "shell", "dumpsys", "package", PKG)
    m = re.search(r"versionCode=(\d+)", out)
    n = re.search(r"versionName=([^\s]+)", out)
    return (m.group(1) if m else "?", n.group(1) if n else "?")


def tv_label(vc, vn, plain=False):
    """Label carried in the tcast INSTALL frame. TCL's dialog does NOT render
    it (its text is fixed); the version is shown only on the PC console.
    Kept for the protocol record / diagnostics."""
    if plain:
        return LABEL_BASE
    tag = RELEASE_NAMES.get(int(vc)) if vc.isdigit() else None
    text = "%s %s / vc%s" % (LABEL_BASE, vn, vc)
    if tag:
        text += " (%s)" % tag
    return text


def push_filename(vc, vn):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", vn)
    return "MyDvResume-v%s-vc%s.apk" % (safe, vc)


def report_after(before):
    """Re-read the installed version so the console shows before -> after."""
    time.sleep(1)
    after = device_version()
    print("=== VERSION CHECK ===", flush=True)
    print("  before : versionCode=%s versionName=%s" % before, flush=True)
    print("  after  : versionCode=%s versionName=%s" % after, flush=True)
    if after[0] == "?":
        print("  (TV did not answer dumpsys; verify manually)", flush=True)
    return after


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


def finish(sock, httpd, grace=GRACE_SECONDS):
    """Graceful teardown after INSTALLED (fixes the spurious "download failed").

    The TV removes the install business session a few hundred ms AFTER
    PACKAGE_ADDED. If the PC closes the tcast socket first, TCastManager sees
    an abnormal session disconnect and tells the launcher the download failed.
    So: keep the heartbeat going, keep the APK HTTP server up, and let the TV
    close the session itself. Give up after `grace` seconds.
    """
    print("  INSTALLED; keeping session alive for TV teardown (<= %ds)..."
          % grace, flush=True)
    deadline = time.monotonic() + grace
    last_beat = time.monotonic()
    buf = b""
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                print("  TV closed the session cleanly", flush=True)
                break
            buf += chunk
        except socket.timeout:
            pass
        except (OSError, ValueError) as e:
            print("  session recv ended:", e, flush=True)
            break
        found, buf = messages(buf)
        for msg in found:
            # Log late states: if a spurious stage=2 ever follows stage=5,
            # it will now be visible instead of being cut off by sock.close().
            if msg.startswith("223"):
                print("  late TV state: %s" % msg[:180], flush=True)
        if time.monotonic() - last_beat > 5:
            try:
                send(sock, "150>>")
            except OSError:
                break
            last_beat = time.monotonic()
    try:
        sock.close()
    except OSError:
        pass
    httpd.shutdown()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--info-only", action="store_true",
                    help="print local + installed versions, do not push")
    ap.add_argument("--plain-label", action="store_true",
                    help="do not append the version to the TV dialog label")
    args = ap.parse_args()

    apk = os.path.join(APK_DIR, APK_NAME)
    if not os.path.isfile(apk):
        print("APK missing:", apk, flush=True)
        return 1

    vc, vn = apk_version(apk)
    digest = file_sha256(apk)
    size = os.path.getsize(apk)
    label = tv_label(vc, vn, args.plain_label)
    tag = RELEASE_NAMES.get(int(vc)) if vc.isdigit() else None

    print("============================================================", flush=True)
    print("  PUSHING   %s%s" % (LABEL_BASE, " " + tag if tag else ""), flush=True)
    print("  versionCode   : %s" % vc, flush=True)
    print("  versionName   : %s" % vn, flush=True)
    print("  APK           : %s (%d bytes)" % (apk, size), flush=True)
    print("  sha256        : %s" % digest, flush=True)
    print("  TV protocol   : %s (TCL dialog text is fixed)" % label, flush=True)
    print("============================================================", flush=True)

    if args.info_only:
        before = device_version()
        print("  TV installed  : versionCode=%s versionName=%s" % before, flush=True)
        return 0

    before = device_version()
    print("  TV installed  : versionCode=%s versionName=%s" % before, flush=True)
    if before[0] != "?" and before[0] == vc:
        print("  (same versionCode -> overwrite install, no bump needed)", flush=True)

    # A versioned copy gives the TV a versioned filename too (some firmware
    # builds show the downloaded file name instead of the label). It is a byte
    # copy of the signed APK and is removed when the process exits.
    name = push_filename(vc, vn)
    push_path = os.path.join(APK_DIR, name)
    shutil.copyfile(apk, push_path)
    atexit.register(lambda: os.path.isfile(push_path) and os.remove(push_path))
    print("  versioned download name: %s" % name, flush=True)

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
        "http://127.0.0.1:%d/%s" % (HTTP_PORT, name),    # via adb reverse
        "http://%s:%d/%s" % (ip, HTTP_PORT, name),        # direct LAN fallback
    ]
    # sizeMB field: the protocol expects an integer number of megabytes; keep
    # the previously verified "1" for any APK below 1 MiB.
    size_mb = str(max(1, (size + (1 << 20) - 1) // (1 << 20)))
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
        send(sock, ">>".join(["223", "INSTALL", PKG, label, url, "2", vc,
                              size_mb, "", "", "", path_md5]))
        print("  INSTALL frame: label=%r versionCode=%s sizeMB=%s"
              % (label, vc, size_mb), flush=True)
        print("  INSTALL request sent; waiting for 同意 on the TV...", flush=True)

        buf = b""
        attempt_done = False
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
                            rc = finish(sock, httpd)
                            report_after(before)
                            return rc
                    elif parts[1] == "PROGRESS":
                        stage, pct = parts[4], parts[5] if len(parts) > 5 else "?"
                        print("  PROGRESS stage=%s percent=%s" % (stage, pct), flush=True)
                        if stage == "5":
                            rc = finish(sock, httpd)
                            report_after(before)
                            return rc
                        if stage == "2":
                            print("  下载/安装失败，尝试下一个 URL", flush=True)
                            attempt_done = True
                        if stage == "4":
                            print("  TCL 验证器拒绝了该 APK（通常是声明了 HOME）", flush=True)
                            sock.close()
                            httpd.shutdown()
                            return 1
                if attempt_done:
                    break  # really move on to the next URL
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
