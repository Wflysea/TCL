#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Enable / disable the on-TV (PC-free) myDV Resume accessibility service.

The APK is installed via TCL 多屏互动 (tcast). For the service to survive
standby and cold boot, system_server must bind it as an accessibility service.
That means registering its ComponentName in secure setting
enabled_accessibility_services, preserving every pre-existing service.

Usage:
    python enable_resume_service.py --status
    python enable_resume_service.py --enable
    python enable_resume_service.py --disable
"""
import os
import subprocess
import sys
import time

TV = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
PKG = "com.wb.mydvresume"
SVC = PKG + "/" + PKG + ".ResumeService"
KEY = "enabled_accessibility_services"
BASE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(BASE, "accessibility_before.txt")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def adb(*args, timeout=30):
    p = subprocess.run([ADB] + list(args), capture_output=True,
                       timeout=timeout, creationflags=NO_WINDOW)
    return (p.stdout + p.stderr).decode("utf-8", "replace").strip()


def connect():
    adb("connect", TV)
    state = adb("-s", TV, "get-state")
    if "device" not in state:
        raise RuntimeError("ADB not connected to %s: %s" % (TV, state))
    return True


def sh(*args):
    return adb("-s", TV, "shell", *args)


def get_services():
    v = sh("settings", "get", "secure", KEY)
    return "" if v in ("null", "none", "") else v


def set_services(value):
    sh("settings", "put", "secure", KEY, value)
    sh("settings", "put", "secure", "accessibility_enabled", "1")


def bound():
    out = sh("dumpsys", "accessibility")
    return [l.strip() for l in out.splitlines()
            if "Bound services" in l or "Enabled services" in l
            or "Crashed services" in l]


def status():
    print("enabled_accessibility_services =", repr(get_services()))
    print("accessibility_enabled =", sh("settings", "get", "secure",
                                        "accessibility_enabled"))
    for line in bound():
        print(" ", line)
    log = sh("logcat", "-d", "-t", "300", "-s", "MyDvResume:I")
    print("--- logcat MyDvResume ---")
    print(log[-1500:] if log else "(no log yet)")


def enable():
    cur = get_services()
    if SVC in cur.split(":"):
        print("already enabled:", cur)
    else:
        if not os.path.isfile(BACKUP) or not open(BACKUP, encoding="utf-8").read().strip():
            with open(BACKUP, "w", encoding="utf-8") as f:
                f.write((cur or "") + "\n")
            print("backup ->", BACKUP, repr(cur))
        parts = [p for p in cur.split(":") if p]
        parts.append(SVC)
        new = ":".join(parts)
        print("writing:", new)
        set_services(new)
    time.sleep(2)
    after = get_services()
    print("readback:", repr(after))
    ok = SVC in after.split(":")
    for line in bound():
        print(" ", line)
    print("RESULT:", "OK" if ok else "FAILED (setting did not stick)")
    return 0 if ok else 1


def disable():
    orig = ""
    if os.path.isfile(BACKUP):
        orig = open(BACKUP, encoding="utf-8").read().strip()
    if not orig:
        parts = [p for p in get_services().split(":") if p and p != SVC]
        orig = ":".join(parts)
    print("restoring:", repr(orig))
    sh("settings", "put", "secure", KEY, orig)
    time.sleep(1)
    print("readback:", repr(get_services()))
    return 0


if __name__ == "__main__":
    connect()
    arg = sys.argv[1] if len(sys.argv) > 1 else "--status"
    if arg == "--enable":
        sys.exit(enable())
    elif arg == "--disable":
        sys.exit(disable())
    else:
        status()
