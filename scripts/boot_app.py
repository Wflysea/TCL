#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TCL「开机进入」组件切换（脱离电脑方案的零 APK 尝试）

  python boot_app.py --status      只读：显示当前值与备份的原值
  python boot_app.py --set-mydv    把开机进入组件指向 myDV
  python boot_app.py --restore     恢复为改动前的原值（com.tcl.cyberui/.MainActivity）

说明:
  * 只改 settings system 的两个键（boot_app_componentname / boot_app_mode），
    不改配置库、不装 APK、不禁用任何应用。全部可逆。
  * 原值备份在 boot_app_original.json（首次 --set-mydv 时自动写入）。
  * 该键由 TCL com.tcl.ttvs 的 MMMService 管理；本机 com.tcl.ttvs 处于禁用状态，
    因此是否生效需实测「待机 → 唤醒」或冷启动。无效时用 --restore 还原即可。
"""
import argparse
import json
import os
import subprocess
import sys

ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
DEV = "192.168.1.26:5555"
PKG = "com.github.mytv.dv"
COMP = PKG + "/.MainActivity"
HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "boot_app_original.json")

NO_WINDOW = 0x08000000
CREATE_NO_WINDOW = 0x08000000


def sh(*args):
    p = subprocess.run([ADB, "-s", DEV, "shell"] + list(args),
                       capture_output=True, timeout=30,
                       creationflags=CREATE_NO_WINDOW)
    return (p.stdout + p.stderr).decode("utf-8", "replace").replace("\r", "").strip()


def connect():
    subprocess.run([ADB, "connect", DEV], capture_output=True, timeout=30,
                   creationflags=CREATE_NO_WINDOW)


def disconnect():
    subprocess.run([ADB, "disconnect", DEV], capture_output=True, timeout=30,
                   creationflags=CREATE_NO_WINDOW)


def get(key):
    return sh("settings", "get", "system", key)


def put(key, val):
    return sh("settings", "put", "system", key, val)


def load_backup():
    if os.path.isfile(BACKUP):
        try:
            with open(BACKUP, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_backup(d):
    with open(BACKUP, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def status():
    connect()
    b = load_backup()
    print("当前 boot_app_componentname =", get("boot_app_componentname"))
    print("当前 boot_app_mode          =", get("boot_app_mode"))
    print("备份原值                    =", b.get("boot_app_componentname", "(无备份)"),
          "/", b.get("boot_app_mode", "(无备份)"))
    print("HOME 桌面                   =",
          sh("cmd", "package", "resolve-activity", "--brief",
             "-c", "android.intent.category.HOME",
             "-a", "android.intent.action.MAIN").splitlines()[-1].strip())
    disconnect()


def set_mydv():
    connect()
    b = load_backup()
    if not b.get("boot_app_componentname"):
        b["boot_app_componentname"] = get("boot_app_componentname")
        b["boot_app_mode"] = get("boot_app_mode")
        save_backup(b)
        print("已备份原值 ->", BACKUP)
    print("set boot_app_componentname =", put("boot_app_componentname", COMP) or COMP)
    # boot_app_mode 原值有值时保持不动（aerial-tv 的建议）
    print("boot_app_mode 保持 =", get("boot_app_mode"))
    print("现在值 =", get("boot_app_componentname"))
    print("请做一次「遥控器电源键待机 → 再按亮屏」实测。")
    disconnect()


def restore():
    connect()
    b = load_backup()
    old = b.get("boot_app_componentname")
    if not old:
        print("没有备份原值，无法自动还原；默认写回 com.tcl.cyberui/.MainActivity")
        old = "com.tcl.cyberui/.MainActivity"
    print("restore boot_app_componentname =", put("boot_app_componentname", old) or old)
    if b.get("boot_app_mode"):
        print("restore boot_app_mode =", put("boot_app_mode", b["boot_app_mode"]))
    print("现在值 =", get("boot_app_componentname"), "/", get("boot_app_mode"))
    disconnect()


def main():
    ap = argparse.ArgumentParser(description="TCL 开机进入组件切换")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true")
    g.add_argument("--set-mydv", action="store_true")
    g.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    try:
        if a.set_mydv:
            set_mydv()
        elif a.restore:
            restore()
        else:
            status()
        return 0
    except Exception as e:
        print("失败:", type(e).__name__, e, file=sys.stderr)
        disconnect()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
