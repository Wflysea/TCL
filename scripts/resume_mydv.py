#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""唤醒后恢复 myDV 画面 —— 仅 Python 标准库，不装 APK、不改电视设置。

现场结论 (TCL tc8000_ay30a2 快速休眠):
  按电源键关屏后，系统把桌面 cyberui 拉回前台；myDV 进程和音频仍在播放
  (MediaSession state=3)，但它的窗口被设为 mViewVisibility=GONE、
  mHasSurface=false / NO_SURFACE -> 所以「只有声音、没有画面」。
解法:
  am start -n com.github.mytv.dv/.MainActivity --activity-single-top
  实测返回 "Activity not started, its current task has been brought to the front":
  不新建 Activity、不重启进程、PlaybackState 与 updated 时间戳不变，
  窗口恢复 mHasSurface=true，画面立刻回来且播放进度不丢。

用法:
  python resume_mydv.py            # 一次性：立刻把 myDV 带回前台
  python resume_mydv.py --status   # 只读：查看当前前台/窗口/播放状态
  python resume_mydv.py --watch    # 守护：唤醒后自动恢复（需电脑常开）
                                   #   可选 --interval 秒 (默认 2)、--aggressive

守护模式的重要实测结论:
  TCL 待机时「网络 ADB 调试」端口会彻底关闭（5555 连不上、adb device offline），
  所以守护读不到关屏状态，也不会看到 OFF->ON 的过渡。
  因此把「ADB 断连 -> 重新连通」当作唤醒信号；同时保留在线状态下的 OFF->ON
  检测作为兜底。断连期间只做短超时的重连尝试，不会卡死。

注意:
  * 待机/唤醒必须用遥控器电源键；adb 注入 KEYCODE_POWER 关屏后无法远程唤醒。
  * 依赖 ADB 5555 保持开启；用完建议关掉电视的「网络 ADB 调试」。
"""
import argparse
import os
import re
import socket
import subprocess
import sys
import time

DEVICE = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
PKG = "com.github.mytv.dv"
ACT = PKG + "/.MainActivity"
HOME = "com.tcl.cyberui"
HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "resume_watch.log")
LOCK_PORT = 47653


def run(*args, timeout=10):
    try:
        kwargs = {"capture_output": True, "timeout": timeout}
        if os.name == "nt":
            # pythonw.exe 自启时没有控制台，避免每次调 adb 都弹出黑框
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        p = subprocess.run(list(args), **kwargs)
        return (p.stdout + p.stderr).decode("utf-8", "replace").replace("\r", "")
    except subprocess.TimeoutExpired:
        return ""
    except Exception as e:
        return "ERR:" + type(e).__name__


def connect(strict=True):
    """strict=False 用于守护循环：连不上不报错，下一轮再试。"""
    run(ADB, "connect", DEVICE, timeout=6)
    if not strict:
        return True
    out = run(ADB, "devices", timeout=8)
    line = next((l for l in out.splitlines() if DEVICE in l), "")
    if "device" not in line or "unauthorized" in line or "offline" in line:
        raise RuntimeError("电视未授权或不可达: %r" % line)
    return True


def sh(*args, timeout=10):
    return run(ADB, "-s", DEVICE, "shell", *args, timeout=timeout)


def snapshot(timeout=10):
    act = sh("dumpsys", "activity", "activities", timeout=timeout)
    resumed = re.search(r"mResumedActivity:\s*ActivityRecord\{[^ ]+ u0 ([^ /]+)", act)
    front = resumed.group(1) if resumed else "?"
    win = sh("dumpsys", "window", "windows", timeout=timeout)
    seg = ""
    m = re.search(r"Window\{[^}]*%s/%s\.MainActivity\}:(.{0,3000})" %
                  (re.escape(PKG), re.escape(PKG)), win, re.S)
    if m:
        seg = m.group(1)
    ps = sh("ps", "-A", timeout=timeout)
    media = sh("dumpsys", "media_session", timeout=timeout)
    return {
        "front": front,
        "has_surface": "mHasSurface=true" in seg,
        "visible": "mViewVisibility=0x0" in seg,
        "running": PKG in ps,
        "playing": ("package=%s" % PKG) in media and re.search(
            r"state=PlaybackState \{state=3", media) is not None,
    }


def probe(timeout=6):
    """返回 (online, wakefulness, display_state)。offline 时 online=False。"""
    p = sh("dumpsys", "power", timeout=timeout)
    if "mWakefulness=" not in p:
        return False, "?", "?"
    w = re.search(r"mWakefulness=(\w+)", p)
    d = re.search(r"Display Power: state=(\w+)", p)
    return True, (w.group(1) if w else "?"), (d.group(1) if d else "?")


def is_off(st):
    return st[0] != "Awake" or st[1] == "OFF"


def is_on(st):
    return st[0] == "Awake" and st[1] == "ON"


def need_resume(s, aggressive=False, require_playing=True):
    if not s["running"]:
        return False, "myDV 未运行（真断电/冷启动，需手动打开应用）"
    if s["front"] == PKG and s["has_surface"]:
        return False, "myDV 已在前台且窗口正常，无需操作"
    if require_playing and not s["playing"]:
        return False, "myDV 未在播放，不打扰"
    if not aggressive and s["front"] != HOME:
        return False, "前台是 %s（非桌面），可能是你主动切换，跳过" % s["front"]
    return True, "myDV 进程在、窗口无 Surface / 前台是桌面"


def do_resume():
    out = sh("am", "start", "-n", ACT, "--activity-single-top", timeout=10)
    time.sleep(1.5)
    s = snapshot()
    ok = s["front"] == PKG and s["has_surface"]
    print("  %s" % (out.strip().splitlines()[0] if out.strip() else "(no output)"), flush=True)
    print("  结果: 前台=%s  mHasSurface=%s  播放中=%s  -> %s" %
          (s["front"], s["has_surface"], s["playing"],
           "画面已恢复" if ok else "未确认，请人工看屏幕"), flush=True)
    return ok


class _Tee:
    """同时写多个流；pythonw.exe 下 __stdout__ 为 None 时只写文件。"""
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, s):
        for f in self.streams:
            try:
                f.write(s)
            except Exception:
                pass

    def flush(self):
        for f in self.streams:
            try:
                f.flush()
            except Exception:
                pass


def setup_log():
    """watch 模式下把输出同时写控制台(若有)与 resume_watch.log。"""
    f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    sys.stdout = _Tee(getattr(sys, "__stdout__", None), f)
    sys.stderr = _Tee(getattr(sys, "__stderr__", None), f)


def watch(interval, aggressive):
    setup_log()
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        print("已有守护实例在运行（本地端口 %d 被占用），本次退出。" % LOCK_PORT, flush=True)
        return
    connect(strict=False)
    online, w, d = probe()
    prev = (w, d)
    was_offline = not online
    print("守护中 (间隔 %.1fs, aggressive=%s)，初始 %s；Ctrl+C 退出" %
          (interval, aggressive, "离线/待机，等待唤醒" if was_offline else "在线 %s" % (prev,)),
          flush=True)
    while True:
        time.sleep(interval)
        online, w, d = probe()
        cur = (w, d)

        if not online:
            if not was_offline:
                print("%s ADB 断开（电视待机/网络调试关闭），等待唤醒后自动重连..." %
                      time.strftime("%H:%M:%S"), flush=True)
            connect(strict=False)  # 短超时重连，失败就下一轮再试
            was_offline = True
            prev = cur
            continue

        if was_offline:
            print("%s 检测到唤醒（ADB 重新连通）" % time.strftime("%H:%M:%S"), flush=True)
            was_offline = False
            time.sleep(3)  # 等系统把桌面拉起来、播放状态稳定
            s = snapshot()
            ok, why = need_resume(s, aggressive, require_playing=False)
            print("  判断: %s" % why, flush=True)
            if ok:
                do_resume()
            prev = cur
            continue

        # 在线且 ADB 未断过：兼容「屏幕状态确实可见」的机型
        if is_off(prev) and is_on(cur):
            time.sleep(1.5)
            s = snapshot()
            ok, why = need_resume(s, aggressive)
            print("%s 屏幕 OFF->ON: %s" % (time.strftime("%H:%M:%S"), why), flush=True)
            if ok:
                do_resume()
        prev = cur


def main():
    ap = argparse.ArgumentParser(description="唤醒后恢复 myDV 画面")
    ap.add_argument("--status", action="store_true", help="只读查看状态")
    ap.add_argument("--watch", action="store_true", help="守护模式，唤醒时自动恢复")
    ap.add_argument("--aggressive", action="store_true", help="配合 --watch：更灵敏但可能干扰主动切桌面")
    ap.add_argument("--interval", type=float, default=2.0, help="守护轮询间隔秒（默认 2）")
    args = ap.parse_args()
    try:
        if args.watch:
            watch(args.interval, args.aggressive)
            return 0
        connect()
        if args.status:
            s = snapshot()
            print("前台       :", s["front"])
            print("myDV 进程  :", s["running"])
            print("播放中     :", s["playing"])
            print("窗口 Surface:", s["has_surface"], " View可见:", s["visible"])
            print("屏幕状态   :", probe()[1:])
            return 0
        s = snapshot()
        ok, why = need_resume(s, aggressive=True)
        print("判断:", why)
        if not ok:
            print("无需操作。")
            return 0
        return 0 if do_resume() else 1
    except KeyboardInterrupt:
        print("\n守护已停止。")
        return 0
    except Exception as e:
        print("错误: %s" % e, file=sys.stderr)
        return 1
    finally:
        try:
            run(ADB, "disconnect", DEVICE, timeout=6)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
