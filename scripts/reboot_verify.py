#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""One real cold boot + end-to-end verification for the v3 boot launcher.

Usage:
    python reboot_verify.py            # reboot, wait, then report
    python reboot_verify.py --report   # report only (after a manual reboot)

Note: adb reboot is a REAL reboot (network adb comes back by itself).
Never use "input keyevent 26" on this TV - it kills 5555 and cannot wake.
"""
import os
import subprocess
import sys
import time

TV = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
BASE = os.path.dirname(os.path.abspath(__file__))
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
BOOT_TIMEOUT = 240
DONE_TIMEOUT = 170


def adb(*args, timeout=25):
    try:
        p = subprocess.run([ADB] + list(args), capture_output=True,
                           timeout=timeout, creationflags=NO_WINDOW)
        return (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    except Exception as e:
        return "<%s>" % e


def connect():
    for _ in range(6):
        adb("connect", TV)
        if "device" in adb("-s", TV, "get-state", timeout=12):
            return True
        time.sleep(1)
    return False


def sh(*args, timeout=25):
    return adb("-s", TV, "shell", *args, timeout=timeout)


def boot_id():
    return sh("cat", "/proc/sys/kernel/random/boot_id").splitlines()[0].strip()


def focus():
    win = sh("dumpsys", "window")
    if "mCurrentFocus" not in win:
        return "(n/a)"
    return win.split("mCurrentFocus=")[-1].splitlines()[0][:160]


def svc_log():
    return sh("logcat", "-d", "-t", "30000", "-s", "MyDvResume:V", timeout=40)


def wait_online():
    print("等待电视重新上线（最多 %d 秒）..." % BOOT_TIMEOUT, flush=True)
    deadline = time.monotonic() + BOOT_TIMEOUT
    while time.monotonic() < deadline:
        adb("connect", TV, timeout=12)
        st = adb("-s", TV, "get-state", timeout=12)
        if "device" in st:
            bc = sh("getprop", "sys.boot_completed", timeout=12).strip()
            if bc == "1":
                print("  电视已上线，boot_completed=1", flush=True)
                return True
        time.sleep(3)
    print("  超时：电视未在 %d 秒内恢复网络 ADB" % BOOT_TIMEOUT, flush=True)
    return False


def wait_boot_session():
    print("等待服务的开机会话结束（最多 %d 秒）..." % DONE_TIMEOUT, flush=True)
    deadline = time.monotonic() + DONE_TIMEOUT
    while time.monotonic() < deadline:
        log = svc_log()
        if "BOOT done" in log or "BOOT cancelled" in log:
            print("  开机会话已结束", flush=True)
            return True
        time.sleep(6)
    print("  未等到 BOOT done（可能日志被开机洪峰冲掉，继续读状态）", flush=True)
    return False


def report(before_id=""):
    print("=== 冷启动核对 ===")
    now_id = boot_id()
    print("  boot_id before:", before_id or "(n/a)")
    print("  boot_id after :", now_id)
    print("  changed       :", bool(before_id) and before_id != now_id)
    print("  uptime        :", sh("cat", "/proc/uptime").splitlines()[0][:40])
    print("  当前前台      :", focus())
    print("=== 服务日志（BOOT / last） ===")
    log = svc_log()
    for line in log.splitlines():
        if "MyDvResume:" in line and ("BOOT" in line or "last=" in line
                                      or "service connected" in line):
            print(" ", line.strip()[:200])
    print("=== boot_target.py 判定 ===")
    p = subprocess.run([sys.executable, os.path.join(BASE, "boot_target.py"),
                        "--boot-report"], capture_output=True, timeout=120)
    print((p.stdout + p.stderr).decode("utf-8", "replace"))


def main():
    if not connect():
        print("ERR: ADB offline（请先唤醒电视）")
        return 1
    before = boot_id()
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--report":
        report(before)
        return 0

    print("=== reboot 前状态 ===")
    print("  boot_id :", before)
    print("  uptime  :", sh("cat", "/proc/uptime").splitlines()[0][:40])
    print("  前台    :", focus())
    print("  目标配置:", sh("settings", "get", "system", "wb_boot_target"))
    print("=== 执行 adb reboot（会打断观看约 1-2 分钟） ===", flush=True)
    print(" ", adb("-s", TV, "reboot", timeout=25), flush=True)
    adb("disconnect", TV, timeout=12)
    time.sleep(5)

    if not wait_online():
        return 1
    time.sleep(8)
    wait_boot_session()
    report(before)
    return 0


if __name__ == "__main__":
    sys.exit(main())
