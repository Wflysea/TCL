#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""End-to-end verification helper for the PC-free myDV resume service.

Usage:
    python verify_resume.py --status      # read-only snapshot
    python verify_resume.py --clear      # clear logcat before a manual test
    python verify_resume.py --report     # after standby/wake, read service log
"""
import os
import subprocess
import sys

TV = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
PKG = "com.wb.mydvresume"
SVC = PKG + "/" + PKG + ".ResumeService"
MARKERS = ("service connected", "SCREEN_OFF", "WAKE via broadcast",
           "WAKE by poll", "WAKE via poll", "WAKE via rebind",
           "HOME after wake", "launched com.github.mytv.dv", "launch failed")
# Wake-ups make the TV emit thousands of system log lines; 3000 was not enough
# to keep the service's own WAKE lines in the buffer. 20000 keeps the full chain.
LOG_LINES = "20000"


def adb(*args, timeout=40):
    try:
        p = subprocess.run([ADB] + list(args), capture_output=True,
                           timeout=timeout, creationflags=NO_WINDOW)
        return (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    except Exception as e:
        return "<%s>" % e


def connect():
    for _ in range(3):
        adb("connect", TV)
        if "device" in adb("-s", TV, "get-state"):
            return True
    return False


def sh(*args):
    return adb("-s", TV, "shell", *args)


def snapshot():
    print("=== 前台窗口 ===")
    print(sh("dumpsys", "window") .split("mCurrentFocus=")[-1].splitlines()[0][:160]
          if "mCurrentFocus" in sh("dumpsys", "window") else "(n/a)")
    print("=== 无障碍服务绑定 ===")
    for line in sh("dumpsys", "accessibility").splitlines():
        if any(k in line for k in ("Bound services", "Enabled services",
                                   "Crashed services", "myDV Resume")):
            print(" ", line.strip()[:200])
    print("=== 服务进程 ===")
    print(sh("pidof", PKG) or "(no process)")
    print("=== myDV 窗口可见性 ===")
    out = sh("dumpsys", "window", "windows")
    for line in out.splitlines():
        if "mViewVisibility" in line or "mHasSurface" in line or "NO_SURFACE" in line:
            print(" ", line.strip()[:160])
    print("=== 待机冻结/快速待机配置 ===")
    for key in ("tcl_fastHibernate", "freezeProcessList",
                "standby_save_bootsource"):
        print(" ", key, "=", sh("settings", "get", "system", key))
    print("=== 自启动策略 ===")
    print(" ", sh("cmd", "appops", "get", PKG).replace("\n", " | "))
    print("=== 电池白名单 ===")
    wl = sh("cmd", "deviceidle", "whitelist")
    print("  myDV:", "com.github.mytv.dv" in wl,
          " resume:", PKG in wl)


def report():
    log = sh("logcat", "-d", "-t", LOG_LINES, "-s", "MyDvResume:V")
    lines = [l for l in log.splitlines() if "MyDvResume:" in l]
    print("=== MyDvResume 日志 (%d 行) ===" % len(lines))
    for l in lines[-40:]:
        print(" ", l)
    print("=== 判定 ===")
    joined = "\n".join(lines)
    for m in MARKERS:
        print("  %-32s %s" % (m, "YES" if m in joined else "-"))
    wake = any(k in joined for k in ("WAKE via broadcast", "WAKE by poll",
                                     "WAKE via poll", "WAKE via rebind"))
    launched = "launched com.github.mytv.dv" in joined
    if wake and launched:
        print("  => 服务已捕获唤醒并把 myDV 拉回前台，端到端成功")
    elif not wake:
        print("  => 未捕获到唤醒事件；请用遥控器电源键做一次待机+唤醒再测")
    else:
        print("  => 捕获到唤醒但未拉回，请检查 launch failed / 时间窗日志")


if __name__ == "__main__":
    if not connect():
        print("ADB 未连上电视（待机时 5555 会断开，请先唤醒电视）")
        sys.exit(1)
    arg = sys.argv[1] if len(sys.argv) > 1 else "--status"
    if arg == "--clear":
        sh("logcat", "-c")
        print("logcat 已清空；请打开 myDV 播放 -> 遥控器电源键待机 -> 再按一次唤醒")
    elif arg == "--report":
        report()
    else:
        snapshot()
