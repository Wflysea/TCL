#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fully undo the PC-free myDV Resume solution.

Removes the accessibility registration (restoring TCL's original 小T助手),
then uninstalls the APK. Battery whitelist / appops die with the package.
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


def adb(*args, timeout=40):
    try:
        p = subprocess.run([ADB] + list(args), capture_output=True,
                           timeout=timeout, creationflags=NO_WINDOW)
        return (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    except Exception as e:
        return "<%s>" % e


def connect():
    for _ in range(5):
        adb("connect", TV)
        if "device" in adb("-s", TV, "get-state"):
            return True
        time.sleep(1)
    return False


def sh(*args):
    return adb("-s", TV, "shell", *args)


def main():
    if not connect():
        print("ERR: ADB offline (wake the TV first)")
        return 1
    orig = ""
    if os.path.isfile(BACKUP):
        orig = open(BACKUP, encoding="utf-8").read().strip()
    if not orig:
        cur = sh("settings", "get", "secure", KEY)
        orig = ":".join(p for p in cur.split(":") if p and p != SVC)
    print("restore accessibility services ->", repr(orig))
    sh("settings", "put", "secure", KEY, orig)
    time.sleep(1)
    print("readback:", sh("settings", "get", "secure", KEY))
    print("=== clear v3 boot config ===")
    for k in ("wb_boot_target", "wb_boot_whitelist", "wb_quiet_mydv",
              "wb_exact_resume"):
        sh("settings", "delete", "system", k)
        print(" ", k, "=", sh("settings", "get", "system", k))
    print("uninstall:", sh("pm", "uninstall", PKG))
    time.sleep(1)
    print("pm path after:", sh("pm", "path", PKG) or "(gone)")
    print("DONE. myDV itself and all earlier debloat/hardening are untouched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
