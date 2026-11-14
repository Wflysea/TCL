#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「待机接着播」体检 / 加固助手 —— 仅 Python 标准库，针对 TCL tc8000_ay30a2 + myDV。

用法:
  python check_standby_resume.py             # 默认：只读体检，逐项报告，不改电视
  python check_standby_resume.py --harden                  # 可逆加固（deviceidle 白名单 + 自启授权）
  python check_standby_resume.py --harden --disable-guard # 上面 + 禁用 com.tcl.guard
  python check_standby_resume.py --disable-extra com.tcl.appmarket2   # 额外禁用厂商应用（可重复/逗号分隔）
  python check_standby_resume.py --unharden               # 撤销全部改动（含恢复 guard 与额外禁用的包）

设计原则:
  * 默认只读。所有会改电视的动作都必须显式指定。
  * 禁用 com.tcl.guard 会连带失去 USB 装 APK / 在线客服，只有显式 --disable-guard 才做。
  * 所有由本脚本禁用的包都记在 standby_harden_state.json，--unharden 会自动恢复；
    原本就处于禁用状态的包不会被记录，撤销时也不会被误启用。
  * 不改 TCL 配置库。
  * 固件升级后可重跑本脚本，看 freeze 名单 / 后台策略有没有被改回。

状态标记: [OK] 符合预期  [WARN] 有隐患  [INFO] 仅供参考/需人工确认
"""
import argparse
import json
import os
import re
import subprocess
import sys

DEVICE = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
PKG = "com.github.mytv.dv"
CONFIG_URI = "content://com.tcl.providers.config/all"
OTA = ["com.tcl.versionUpdateApp", "com.tcl.ttvs", "com.snm.upgrade"]
GUARD = "com.tcl.guard"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standby_harden_state.json")


def run(*args, timeout=90):
    p = subprocess.run(list(args), capture_output=True, timeout=timeout)
    return (p.stdout + p.stderr).decode("utf-8", "replace").replace("\r", "")


def sh(*args, timeout=90):
    return run(ADB, "-s", DEVICE, "shell", *args, timeout=timeout)


def connect():
    run(ADB, "connect", DEVICE, timeout=30)
    out = run(ADB, "devices", timeout=30)
    line = next((l for l in out.splitlines() if DEVICE in l), "")
    if "device" not in line or "unauthorized" in line or "offline" in line:
        raise RuntimeError("电视未授权或不可达: %r\n%s" % (line, out))


def settings(ns, key):
    return sh("settings", "get", ns, key).strip()


def settings_list(ns):
    out = sh("settings", "list", ns, timeout=90)
    d = {}
    for l in out.splitlines():
        if "=" in l:
            k, v = l.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def configs():
    """把 content://com.tcl.providers.config/all 解析成 {project_id: {name: value}}"""
    out = sh("content", "query", "--uri", CONFIG_URI, timeout=120)
    res = {}
    for line in out.splitlines():
        m = re.search(r"project_id=([^,]+),\s*config_content=(\[.*\]|\{.*\})\s*$", line)
        if not m:
            continue
        pid = m.group(1).strip()
        try:
            raw = json.loads(m.group(2))
            if isinstance(raw, list):
                res[pid] = {x.get("name"): x.get("value") for x in raw if isinstance(x, dict)}
            else:
                res[pid] = raw
        except Exception:
            res[pid] = {"_raw": m.group(2)}
    return res, out


def disabled_packages():
    out = sh("pm", "list", "packages", "-d", timeout=90)
    return {l.strip()[len("package:"):] for l in out.splitlines() if l.strip().startswith("package:")}


def report():
    connect()
    cfg, cfg_raw = configs()
    dis = disabled_packages()
    sysset = settings_list("system")
    secset = settings_list("secure")
    globset = settings_list("global")

    def line(status, title, detail):
        print("[%-4s] %s\n         %s" % (status, title, detail))

    print("=" * 66)
    print("待机接着播 · 体检报告   (固件 %s)" % sh("getprop", "ro.build.display.id").strip())
    print("=" * 66)

    # 1. 待机类型
    fz = cfg.get("freeze", {})
    hibernate = fz.get("tcl_fastHibernate")
    plist = fz.get("freezeProcessList") or []
    if isinstance(plist, str):
        plist = re.findall(r'"([^"]+)"', plist)
    hit = PKG in plist
    line("OK" if (str(hibernate).lower() == "true" and not hit) else "WARN",
         "1. 待机机制：快速休眠、myDV 不被冻结",
         "tcl_fastHibernate=%s；冻结名单 %d 项；myDV %s名单内" %
         (hibernate, len(plist), "在" if hit else "不在"))

    # 2. 唤醒回原应用
    bootsrc = sysset.get("standby_save_bootsource", settings("system", "standby_save_bootsource"))
    line("OK" if bootsrc == "1" else "WARN",
         "2. 待机保存启动源",
         "standby_save_bootsource=%s（1=唤醒回原应用）" % bootsrc)

    # 3. 待机清理黑名单
    sb = cfg.get("StandbyProcess", {})
    bl = sb.get("standbyProcessBlackList") or []
    if isinstance(bl, str):
        bl = re.findall(r'"([^"]+)"', bl)
    line("OK" if PKG not in bl else "WARN",
         "3. 待机进程清理黑名单",
         "黑名单 %d 项（含 TVBox 等直播应用）；myDV %s其中" % (len(bl), "在" if PKG in bl else "不在"))

    # 4. 电视卫士内存清理
    g = cfg.get("TGuardMemoryManager", {})
    kw = g.get("KillWhiteList") or []
    ow = g.get("OneKeyCleanWhiteList") or []
    for name in ("kw", "ow"):
        v = kw if name == "kw" else ow
        if isinstance(v, str):
            v = re.findall(r'"([^"]+)"', v)
        if name == "kw":
            kw = v
        else:
            ow = v
    kill_on = str(g.get("KillEnable")).lower() == "true"
    reclaim_on = str(g.get("ReclaimEnable")).lower() == "true"
    miss = PKG not in kw and PKG not in ow
    guard_off = GUARD in dis
    risk = miss and (kill_on or reclaim_on) and not guard_off
    line("WARN" if risk else "OK",
         "4. 电视卫士 / 一键清理白名单 —— 清单第 2 条的实证",
         "KillEnable=%s ReclaimEnable=%s；白名单 %d/%d 项，myDV 均%s；电视卫士 %s → %s" %
         (kill_on, reclaim_on, len(kw), len(ow), "不在" if miss else "在",
          "已禁用(清理来源停用)" if guard_off else "仍在运行",
          "会被一键加速/内存回收杀掉" if risk else "风险已解除"))

    # 5. 定时关机 / 自动断电线索
    countdown = globset.get("tcl_app_sysui_countdown_enable", "")
    operate = globset.get("tcl_app_sysui_countdown_operate", "")
    fs = cfg.get("ForceShutdown", {})
    smart = fs.get("smart_audio_to_shutdown_enable", "")
    slp = secset.get("sleep_timeout", settings("secure", "sleep_timeout"))
    cd_on = str(countdown).lower() in ("1", "true")
    line("WARN" if cd_on else "INFO", "5. 定时关机 / 自动断电（需人工在设置里确认）",
         "倒计时关机开关=%s（操作=%s）；ForceShutdown.smart_audio_to_shutdown=%s；sleep_timeout=%s ms(%.0f h)" %
         (countdown or "空/未启用", operate or "未设置", smart or "?", slp, int(slp) / 3600000 if str(slp).isdigit() else 0))

    # 6. OTA 与固件复查
    off = [p for p in OTA if p in dis]
    line("OK" if len(off) == 3 else "WARN",
         "6. OTA 三件套保持禁用（防固件被升改掉 freeze 策略）",
         "已禁用 %d/3：%s" % (len(off), ", ".join(off) or "无"))

    # 7. 冷启动自启（信息项）
    appops = sh("appops", "get", PKG, timeout=60)
    auto = next((l.strip() for l in appops.splitlines() if "AUTO_START" in l), "无记录(默认)")
    idle = sh("cmd", "deviceidle", "whitelist", timeout=60)
    in_idle = PKG in idle
    line("INFO", "7. 冷启动自启（不影响待机续播，断电才相关）",
         "%s；deviceidle 白名单含 myDV=%s；boot_app_componentname=%s" %
         (auto, in_idle, sysset.get("boot_app_componentname", "?")))

    # 8. 当前运行状态
    # 注意：uk.cctv6.mytv.legacz 等应用的进程名也含 "mytv"，用子串匹配
    # 会把别的应用误报成「myDV 运行中」。改用 pidof 精确判定。
    pid = sh("pidof", PKG).strip().split()
    running = bool(pid) and pid[0].isdigit()
    up = sh("uptime").strip()
    detail = ("运行中 (pid=%s)" % pid[0]) if running else \
        "未运行（若正在播放却被清掉，见第 4 条）"
    line("INFO" if not running else "OK", "8. myDV 当前进程",
         "%s；系统 %s" % (detail, up))

    # 9. 版本
    dp = sh("dumpsys", "package", PKG, timeout=90)
    ver = re.search(r"versionName=([^\s]+)", dp)
    line("INFO", "9. myDV 版本", "%s（是否为最新请用 update_mydv.py --check 查）" %
         (ver.group(1) if ver else "读取失败"))

    vendor = [GUARD, "com.tcl.appmarket2", "com.tcl.usercenter", "com.tcl.walleve",
              "com.tcl.micmanager", "com.tcl.UpdatePeripheral"]
    line("INFO", "10. 厂商应用禁用状态（远程触达面）",
         ", ".join("%s=%s" % (p.split(".")[-1], "禁用" if p in dis else "启用") for p in vendor))

    print("-" * 66)
    print("人工遵守（脚本改不了，也没替你改）：")
    print("  · 只用遥控器电源键待机；别拔电源、别用真关机、别开定时关机")
    print("  · 别点电视卫士的「一键加速 / 内存清理」，也别设自动清理")
    print("  · 别刷本地 myDV-2.1.37.apk（那是截断残包，且是旧版）")
    print("  · 手动升级固件后，重跑本脚本复查 freeze / TGuard 策略")
    print("=" * 66)


def load_state():
    state = {}
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    state = d
        except Exception:
            pass
    # 兼容早期版本的状态文件（没有 harden_applied 字段）
    if state and "harden_applied" not in state and state.get("commands"):
        state["harden_applied"] = True
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def harden(undo=False, disable_guard=False, do_harden=False, extra=None):
    connect()
    state = load_state()
    extra = [p.strip() for p in (extra or []) if p.strip()]

    if undo:
        if not state:
            print("没有找到加固记录，无需撤销。")
            return
        if state.get("harden_applied"):
            for c in [
                ("cmd", "deviceidle", "whitelist", "-" + PKG),
                ("appops", "set", PKG, "APP_AUTO_START", "ignore"),
                ("appops", "set", PKG, "APP_ASSOC_START", "default"),
            ]:
                print("  %s -> %s" % (" ".join(c), sh(*c, timeout=60).strip() or "(ok)"))
        if state.get("guard_disabled"):
            print("  pm enable %s -> %s" % (GUARD, sh("pm", "enable", GUARD, timeout=60).strip() or "(ok)"))
        for pkg in state.get("extra_disabled", []):
            print("  pm enable %s -> %s" % (pkg, sh("pm", "enable", pkg, timeout=60).strip() or "(ok)"))
        os.remove(STATE_FILE)
        print("已撤销全部加固。")
        return

    if do_harden:
        cmds = [
            ("cmd", "deviceidle", "whitelist", "+" + PKG),
            ("appops", "set", PKG, "APP_AUTO_START", "allow"),
            ("appops", "set", PKG, "APP_ASSOC_START", "allow"),
        ]
        for c in cmds:
            print("  %s -> %s" % (" ".join(c), sh(*c, timeout=60).strip() or "(ok)"))
        state["package"] = PKG
        state["harden_applied"] = True
        state["commands"] = [" ".join(c) for c in cmds]

    if disable_guard:
        before = GUARD in disabled_packages()
        if before:
            print("  %s 原本就是禁用状态，跳过" % GUARD)
        else:
            out = sh("pm", "disable-user", GUARD, timeout=60)
            print("  pm disable-user %s -> %s" % (GUARD, out.strip() or "(ok)"))
            if GUARD not in disabled_packages():
                raise RuntimeError("禁用 %s 未生效" % GUARD)
            state["guard_disabled"] = True
            state["guard_was_disabled_before"] = before

    dis = disabled_packages()
    changed = []
    for pkg in extra:
        if pkg in dis:
            print("  %s 原本已禁用，跳过（撤销时不会动它）" % pkg)
            continue
        if not sh("pm", "list", "packages", pkg, timeout=60).strip().startswith("package:"):
            print("  %s 不存在，跳过" % pkg)
            continue
        out = sh("pm", "disable-user", pkg, timeout=60)
        print("  pm disable-user %s -> %s" % (pkg, out.strip() or "(ok)"))
        if pkg in disabled_packages():
            changed.append(pkg)
            dis.add(pkg)
        else:
            print("    警告：禁用未生效，不记入撤销清单")
    if changed:
        state["extra_disabled"] = list(dict.fromkeys(state.get("extra_disabled", []) + changed))
        state.setdefault("package", PKG)

    if not (do_harden or (disable_guard and state.get("guard_disabled")) or changed):
        print("没有需要执行的改动。")
        return
    save_state(state)
    print("完成，记录:", STATE_FILE)
    print("撤销全部改动: python check_standby_resume.py --unharden")


def main():
    ap = argparse.ArgumentParser(description="待机接着播体检/加固")
    ap.add_argument("--harden", action="store_true", help="执行可逆加固")
    ap.add_argument("--disable-guard", action="store_true", help="禁用 com.tcl.guard")
    ap.add_argument("--disable-extra", action="append", metavar="PKG",
                    help="额外禁用一个厂商应用，可重复或逗号分隔；撤销时自动恢复")
    ap.add_argument("--unharden", action="store_true", help="撤销全部加固")
    args = ap.parse_args()
    extra = []
    for x in (args.disable_extra or []):
        extra += [p.strip() for p in x.split(",") if p.strip()]
    try:
        if args.unharden and (args.harden or args.disable_guard or extra):
            raise RuntimeError("--unharden 不能与 --harden / --disable-guard / --disable-extra 同时用")
        if args.unharden:
            harden(undo=True)
        elif args.harden or args.disable_guard or extra:
            harden(disable_guard=args.disable_guard, do_harden=args.harden, extra=extra)
        else:
            report()
        return 0
    except Exception as e:
        print("错误: %s" % e, file=sys.stderr)
        return 1
    finally:
        try:
            run(ADB, "disconnect", DEVICE, timeout=15)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
