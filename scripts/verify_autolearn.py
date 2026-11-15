#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Read-only verification of the v4.2 AUTO-LEARNING resume service.

Usage:
    python verify_autolearn.py                     # full report
    python verify_autolearn.py --follow           # report + tail of service log
    python verify_autolearn.py --clear-log        # clear logcat before a test
    python verify_autolearn.py --auto-learn-on    # settings put system wb_auto_learn 1
    python verify_autolearn.py --auto-learn-off   # settings put system wb_auto_learn 0
    python verify_autolearn.py --exclude "a,b"    # never resume these packages
    python verify_autolearn.py --allow-autostart  # OPTIONAL: TCL cold-boot appops

What to look for after installing a NEW app on the TV (no PC needed):
    service connected v4.2 (auto-learn), userApps=N
    auto-learn scan (bind|standby|wake): N user apps, M new components [...]
    auto-learn PACKAGE_ADDED: <pkg> component=<flattened component>
    WAKE target from standby record=<pkg>
    launched <pkg> (task reuse) top=<activity>

The service itself learns new packages; this script only *reads* the evidence.
The optional --allow-autostart is for cold-boot only: a third-party app cannot
set TCL's APP_AUTO_START/APP_ASSOC_START appops on other packages.
"""
from __future__ import print_function

import argparse
import os
import subprocess
import time

TV = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
PKG = "com.wb.mydvresume"
EXPECT_VC = "20"
EXPECT_VN = "3.4"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Mirrors ResumeService.SKIP_PKGS: never resumed, so not counted as learnable.
SKIP = {
    PKG, "com.tcl.cyberui", "com.tcl.MultiScreenInteraction_TV",
    "com.tcl.appmarket2", "com.tcl.guard", "com.android.settings",
    "com.android.systemui", "com.android.packageinstaller",
    "com.android.vending", "android",
}


def adb(*args, **kwargs):
    timeout = kwargs.pop("timeout", 40)
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


def setting(key, ns="system"):
    return sh("settings", "get", ns, key)


def put(key, value):
    sh("settings", "put", "system", key, value)
    return setting(key)


def mark(ok):
    return "PASS" if ok else "FAIL"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--follow", action="store_true", help="also print service log tail")
    ap.add_argument("--clear-log", action="store_true", help="clear logcat, then exit")
    ap.add_argument("--auto-learn-on", action="store_true")
    ap.add_argument("--auto-learn-off", action="store_true")
    ap.add_argument("--exclude", help="comma-separated packages to exclude")
    ap.add_argument("--allow-autostart", action="store_true",
                    help="optional cold-boot appops for all user apps")
    args = ap.parse_args()

    if not connect():
        print("ERR: ADB offline (wake the TV first)")
        return 1

    if args.clear_log:
        sh("logcat", "-c")
        print("logcat cleared; now install an app / do a standby-wake, then re-run")
        return 0
    if args.auto_learn_on or args.auto_learn_off:
        print("wb_auto_learn =", put("wb_auto_learn",
                                     "0" if args.auto_learn_off else "1"))
        return 0
    if args.exclude is not None:
        print("wb_learn_exclude =", put("wb_learn_exclude", args.exclude))
        return 0
    if args.allow_autostart:
        pkgs = [l.strip()[len("package:"):] for l in
                sh("pm", "list", "packages", "-3").splitlines()
                if l.strip().startswith("package:")]
        for p in pkgs:
            if p in SKIP:
                continue
            sh("cmd", "appops", "set", p, "APP_AUTO_START", "allow")
            sh("cmd", "appops", "set", p, "APP_ASSOC_START", "allow")
        print("allowed autostart for %d user app(s) (cold-boot only, optional)"
              % len([p for p in pkgs if p not in SKIP]))
        return 0

    print("=== installed version ===")
    dump = sh("dumpsys", "package", PKG)
    vc = vn = ""
    for line in dump.splitlines():
        if "versionCode=" in line and not vc:
            vc = line.split("versionCode=")[1].split()[0]
        if "versionName=" in line and not vn:
            vn = line.split("versionName=")[1].split()[0]
    print("  versionCode=%s versionName=%s  [%s]"
          % (vc, vn, mark(vc == EXPECT_VC and vn == EXPECT_VN)))

    print("=== accessibility binding ===")
    acc = sh("dumpsys", "accessibility")
    bound = "myDV Resume" in acc and "Bound services" in acc
    print("  [%s] myDV Resume bound" % mark(bound))
    print("  enabled_accessibility_services =",
          setting("enabled_accessibility_services", "secure")[:200])

    print("=== config ===")
    for key in ("wb_auto_learn", "wb_learn_exclude", "wb_boot_whitelist",
                "wb_boot_target", "wb_quiet_mydv"):
        print("  %-20s = %s" % (key, setting(key)[:180]))

    print("=== user-installed packages on device ===")
    pkgs = sorted(set(l.strip()[len("package:"):] for l in
                      sh("pm", "list", "packages", "-3").splitlines()
                      if l.strip().startswith("package:")))
    learnable = [p for p in pkgs if p not in SKIP]
    print("  %d installed, %d learnable" % (len(pkgs), len(learnable)))

    print("=== service log evidence ===")
    log = sh("logcat", "-d", "-v", "brief", "-s", "MyDvResume:V", "-t", "5000")
    lines = log.splitlines()
    scans = [l for l in lines if "auto-learn scan" in l]
    added = [l for l in lines if "auto-learn PACKAGE_ADDED" in l]
    connected = [l for l in lines if "service connected v4.2" in l]
    wakes = [l for l in lines if "WAKE " in l]
    launches = [l for l in lines if "launched " in l]
    bad = [l for l in lines if ("no launchable component" in l
                                or "legacy fallback" in l
                                or "task-reuse launch failed" in l)]

    def tail(items, n=3):
        for l in items[-n:]:
            print("   ", l.strip()[:220])
        if not items:
            print("    (none)")

    print("  -- service bound --"); tail(connected, 2)
    print("  -- last scan --"); tail(scans, 3)
    print("  -- new apps learned --"); tail(added, 8)
    print("  -- wake decisions --"); tail(wakes, 5)
    print("  -- launches --"); tail(launches, 6)

    learned_ok = bool(scans or connected)
    print("  [%s] auto-learn scan/connect evidence present" % mark(learned_ok))
    if bad:
        print("  [WARN] %d fallback/error line(s):" % len(bad))
        tail(bad, 5)
    else:
        print("  [PASS] no unresolved component / legacy fallback")

    mydv_launch = len([l for l in launches
                       if "launched com.github.mytv.dv" in l])
    other_launch = len([l for l in launches
                        if "launched " in l
                        and "launched com.github.mytv.dv" not in l])
    print("  launches: other apps=%d, myDV(default)=%d" % (other_launch, mydv_launch))

    if args.follow:
        print("=== log tail ===")
        tail(lines, 40)

    print("""
NOTE: a real check needs the TV remote:
  1) install any new app, open it, pause playback;
  2) press POWER to standby, press POWER again to wake;
  3) re-run `python verify_autolearn.py --follow` and confirm
     `WAKE target from standby record=<new pkg>` + `launched <new pkg> (task reuse)`.
Never use `input keyevent 26` -- it drops adb on this TV.""")
    return 0 if (vc == EXPECT_VC and bound) else 1


if __name__ == "__main__":
    raise SystemExit(main())
