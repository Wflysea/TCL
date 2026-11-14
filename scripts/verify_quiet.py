#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Verify the v3.5 fix: no stray myDV audio after a REAL standby/wake.

Typical use:
    python verify_quiet.py --clear        # BEFORE standby (screen must be on)
    ... press TV power button to standby, then wake ...
    python verify_quiet.py --report       # judge the result

--report only accepts a REAL standby/wake: it requires a SCREEN_OFF, then a
WAKE after it, then a quiet action after that. A cold boot's SCREEN_ON or a
simulated accessibility rebind alone is NOT enough, so stale logs cannot
produce a false "pass".

The script is read-only except for --clear (logcat -c).
"""
import os
import re
import subprocess
import sys
import time

TV = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
PKG = "com.wb.mydvresume"
MYDV = "com.github.mytv.dv"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
LOG_LINES = "30000"
TS = re.compile(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})\.(\d{3})")


def adb(*args, timeout=45):
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


def ts(line):
    """Comparable (month, day, hour, min, sec, msec) tuple, or None."""
    m = TS.match(line)
    return tuple(int(x) for x in m.groups()) if m else None


def mydv_uid():
    for line in sh("dumpsys", "package", MYDV).splitlines():
        if "userId=" in line:
            try:
                return line.split("userId=")[1].split()[0].strip()
            except Exception:
                pass
    return "10040"


def report():
    uid = mydv_uid()
    log = sh("logcat", "-d", "-t", LOG_LINES, "-s", "MyDvResume:V")
    lines = [l.strip() for l in log.splitlines() if "MyDvResume:" in l]
    offs = [l for l in lines if "SCREEN_OFF" in l]
    wakes = [l for l in lines if "WAKE via" in l]
    quiet = [l for l in lines if "quiet myDV background audio" in l]
    skipped = [l for l in lines if "quiet skipped" in l]
    launched = [l for l in lines if "launched " in l and "BOOT" not in l]

    print("=== 服务日志 ===")
    if offs:
        print("  最近待机      :", offs[-1][:150])
    else:
        print("  最近待机      : (无 SCREEN_OFF)")
    for l in wakes[-3:]:
        print(" ", l[:160])
    print("  quiet 执行次数 :", len(quiet))
    for l in quiet[-4:]:
        print(" ", l[:160])
    if skipped:
        print("  quiet 跳过(myDV 在前台) :", len(skipped), "次")
    for l in launched[-3:]:
        print(" ", l[:160])

    print("\n=== 当前状态 ===")
    pid = sh("pidof", MYDV)
    print("  myDV 进程      :", pid or "(无，已被清理)")
    players = sh("dumpsys", "audio")
    section = players.split("players:")[-1].split("ducked players")[0] \
        if "players:" in players else ""
    mydv_tracks = [l.strip() for l in section.splitlines()
                   if ("u/pid:%s/" % uid) in l]
    started = [l for l in mydv_tracks if "state:started" in l]
    for l in mydv_tracks:
        print("  myDV 音轨      :", l[:150])
    if not mydv_tracks:
        print("  myDV 音轨      : (无)")
    print("  前台           :",
          sh("dumpsys", "window").split("mCurrentFocus=")[-1].splitlines()[0][:150])
    q = sh("settings", "get", "system", "wb_quiet_mydv")
    print("  wb_quiet_mydv  :", q, "(null/1 = 开启，0/off = 关闭)")

    # ---- timeline judgement: SCREEN_OFF -> WAKE -> quiet ----
    t_off = ts(offs[-1]) if offs else None
    wake_after = [l for l in wakes
                  if t_off is None or (ts(l) and ts(l) >= t_off)]
    t_wake = ts(wake_after[0]) if wake_after else None
    quiet_after = [l for l in quiet
                   if t_wake and ts(l) and ts(l) >= t_wake]
    wake_line = wake_after[0] if wake_after else ""
    target_is_mydv = "target=%s" % MYDV in wake_line

    print("\n=== 判定 ===")
    if q and q.strip() in ("0", "off"):
        print("  => 静音开关已关闭，当前是旧行为")
    elif not offs:
        print("  => 这不是一次真实待机唤醒：日志里没有 SCREEN_OFF")
        print("     （开机点亮的 SCREEN_ON、模拟重绑定都不算。）")
        print("     请先跑 --clear，再用遥控器电源键待机→唤醒，最后跑 --report")
    elif not wake_after:
        print("  => 待机后未捕获唤醒事件；确认已用遥控器唤醒，或稍等几秒再测")
    elif target_is_mydv:
        print("  => 本次唤醒目标就是 myDV，静音按设计跳过，无法验证「进别的应用」场景")
        print("     请在别的应用播放时待机再唤醒")
    elif not quiet_after:
        print("  => 唤醒了但唤醒后没执行 quiet：检查服务版本是否 1.8 / 目标是否可启动")
    elif started:
        print("  => 仍有 myDV started 音轨：TCL 可能在最后一次补刀之后又恢复了播放")
    else:
        print("  => 通过：真实待机唤醒进别的应用后，myDV 后台音频已清除")
        print("     时序: SCREEN_OFF %s -> WAKE %s -> quiet x%d"
              % (offs[-1][:18], wake_after[0][:18], len(quiet_after)))


if __name__ == "__main__":
    if not connect():
        print("ADB 未连上电视（待机时 5555 会断开，请先用遥控器唤醒）")
        sys.exit(1)
    arg = sys.argv[1] if len(sys.argv) > 1 else "--report"
    if arg == "--clear":
        sh("logcat", "-c", "-b", "all")
        print("日志已清空。请用遥控器电源键待机，再唤醒，然后跑 --report")
        print("（待机时网络 ADB 会断开属正常；不要用 adb 注入电源键）")
    else:
        report()
