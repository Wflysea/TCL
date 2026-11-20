#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run after push_apk.py: re-apply TCL boot-policy exemptions and re-bind v3.

An APK update resets TCL's APP_AUTO_START / APP_ASSOC_START policies and the
usage-stats appop, so this must be re-run after EVERY push.
"""
import os
import subprocess
import time

TV = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
PKG = "com.wb.mydvresume"
SVC = PKG + "/" + PKG + ".ResumeService"
WALLEVE = "com.tcl.walleve/com.tcl.walleve.platform.accessibility.AiAccessibilityService"
KEY = "enabled_accessibility_services"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def adb(*args, timeout=40):
    try:
        p = subprocess.run([ADB] + list(args), capture_output=True,
                           timeout=timeout, creationflags=NO_WINDOW)
        return (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    except Exception as e:
        return "<%s>" % e


def connect():
    for _ in range(6):
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

    print("=== installed version ===")
    d = sh("dumpsys", "package", PKG)
    for line in d.splitlines():
        if "versionName=" in line or "versionCode=" in line:
            print(" ", line.strip()[:160])

    print("=== re-allow autostart (TCL resets this on update) ===")
    sh("cmd", "appops", "set", PKG, "APP_AUTO_START", "allow")
    sh("cmd", "appops", "set", PKG, "APP_ASSOC_START", "allow")

    print("=== allow usage stats (needed to remember the last app) ===")
    sh("cmd", "appops", "set", PKG, "GET_USAGE_STATS", "allow")
    sh("pm", "grant", PKG, "android.permission.PACKAGE_USAGE_STATS")
    ops = sh("cmd", "appops", "get", PKG)
    print(" ", ops.replace("\n", " | "))
    print("  USAGE_STATS lines:", [l.strip() for l in ops.splitlines()
                                   if "USAGE_STATS" in l])

    print("=== boot target config (default: myDV) ===")
    sh("settings", "put", "system", "wb_boot_target", "com.github.mytv.dv")
    print("  wb_boot_target =", sh("settings", "get", "system", "wb_boot_target"))

    print("=== keep battery whitelist ===")
    sh("cmd", "deviceidle", "whitelist", "+" + PKG)

    print("=== ensure accessibility registration + re-bind ===")
    cur = sh("settings", "get", "secure", KEY)
    parts = [p for p in cur.split(":") if p and p != SVC]
    parts.append(SVC)
    target = ":".join(parts)
    sh("settings", "put", "secure", KEY, WALLEVE)
    time.sleep(1)
    sh("settings", "put", "secure", KEY, target)
    sh("settings", "put", "secure", "accessibility_enabled", "1")
    time.sleep(3)

    dump = sh("dumpsys", "accessibility")
    # Judge by the stable component name in the enabled list, not by the app
    # label (which changed myDV Resume -> Resume in v4.5 and broke the old
    # label-based check). Also require an actual "Bound services" entry for
    # our service: dumpsys shows bound services by label, so accept either
    # the current label "Resume" or the legacy "myDV Resume".
    enabled_ok = SVC in dump
    bound_ok = ("Bound services" in dump
                and ("label=Resume" in dump or "label=myDV Resume" in dump))
    ok = enabled_ok and bound_ok
    print("  Bound:", [l.strip()[:180] for l in dump.splitlines()
                       if "Bound services" in l])
    print("=== service log ===")
    print(sh("logcat", "-d", "-v", "brief", "-s", "MyDvResume:V")[-1500:])
    print("RESULT:", "v3 BOUND" if ok else "NOT BOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
