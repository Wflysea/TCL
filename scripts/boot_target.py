#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Configure / inspect the TV-side cold-boot launcher (v3, scheme C).

Usage:
    python boot_target.py --status
    python boot_target.py --list-apps           # all self-installed apps + labels
    python boot_target.py --all-apps            # whitelist ALL launchable user apps
    python boot_target.py --allow-autostart     # let TCL start those apps in background
    python boot_target.py --set com.github.mytv.dv
    python boot_target.py --off
    python boot_target.py --on
    python boot_target.py --whitelist "com.github.mytv.dv,com.tv.qx"
    python boot_target.py --reset               # back to the APK's built-in list
    python boot_target.py --quiet-off           # keep myDV background audio (v3.5 fix off)
    python boot_target.py --quiet-on            # stop myDV background audio (default)
    python boot_target.py --exact-off           # v3.6: disable exact screen restore
    python boot_target.py --exact-on            # v3.6: enable exact screen restore (default)
    python boot_target.py --wake-report         # v3.6: judge last standby -> wake
    python boot_target.py --boot-report

The service reads Settings.System on every check, so changes apply instantly
(no rebind / reboot needed). With the whitelist key empty, the APK's built-in
list of installed launchable apps is used.
"""
import os
import subprocess
import sys
import time

TV = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
PKG = "com.wb.mydvresume"
KEY_TARGET = "wb_boot_target"
KEY_WHITELIST = "wb_boot_whitelist"
KEY_QUIET = "wb_quiet_mydv"
KEY_EXACT = "wb_exact_resume"
DEFAULT_TARGET = "com.github.mytv.dv"
BUILTIN_WHITELIST = {
    "com.github.mytv.dv", "com.ysc.tvbox", "com.cctv.yangshipin.app.androidq",
    "uk.cctv6.mytv.legacz", "com.tv.qx", "app.yecao", "com.local.ktv",
    "cn.toside.music.mobile",
}
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
LOG_LINES = "30000"

# Chinese labels read from each installed APK with `aapt dump badging`.
LABELS = {
    "com.cctv.yangshipin.app.androidq": "欧歌影视",
    "com.github.mytv.dv": "myDV",
    "com.huawei.himovceie": "影视仓(华为通道)",
    "com.ysc.tvbox": "影视仓",
    "com.tv.qx": "千寻",
    "app.yecao": "小草助手TV版",
    "com.local.ktv": "麦动",
    "cn.toside.music.mobile": "ZL-Music",
    "com.bbll.fix": "BBLL fix",
    "com.feicui.tvhd": "翡翠TV",
    "uk.cctv6.mytv.legacz": "乡村电视",
    "com.example.tvwallpaper": "NAS 壁纸",
    "com.android.letv.browser": "TV Browser",
    "com.gitv.dvb.live": "宽带电视",
    "rocks.aston.hongguotv": "红果TV",
    "com.wb.mydvresume": "myDV Resume (本服务)",
}


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


def get(key):
    return sh("settings", "get", "system", key)


def put(key, value):
    sh("settings", "put", "system", key, value)
    return get(key)


def focus():
    win = sh("dumpsys", "window")
    if "mCurrentFocus" not in win:
        return "(n/a)"
    return win.split("mCurrentFocus=")[-1].splitlines()[0][:160]


def app_rows():
    """[(pkg, component_or_empty)] for every user-installed package."""
    out = sh("pm", "list", "packages", "-3")
    pkgs = sorted(set(l.strip()[len("package:"):] for l in out.splitlines()
                      if l.strip().startswith("package:")))
    rows = []
    for p in pkgs:
        comp = ""
        for cat in ("android.intent.category.LEANBACK_LAUNCHER",
                    "android.intent.category.LAUNCHER"):
            r = sh("cmd", "package", "resolve-activity", "--brief",
                   "-a", "android.intent.action.MAIN", "-c", cat, p)
            lines = [x.strip() for x in r.splitlines() if x.strip()]
            if lines and "/" in lines[-1] and "No activity" not in lines[-1]:
                comp = lines[-1]
                break
        rows.append((p, comp))
    return rows


def describe(pkg):
    return "%s (%s)" % (LABELS.get(pkg, "?"), pkg)


def current_whitelist():
    cfg = get(KEY_WHITELIST)
    if cfg and cfg != "null":
        return [x.strip() for x in cfg.split(",") if x.strip()]
    return sorted(BUILTIN_WHITELIST)


def allow_autostart(pkgs):
    """TCL's AppBootPolicy defaults third-party apps to APP_AUTO_START=ignore,
    which blocks the service from bringing them to the foreground."""
    print("=== 放行 TCL 自启动管控 (%d 个应用) ===" % len(pkgs))
    for p in pkgs:
        sh("cmd", "appops", "set", p, "APP_AUTO_START", "allow")
        sh("cmd", "appops", "set", p, "APP_ASSOC_START", "allow")
        ops = sh("cmd", "appops", "get", p)
        hit = [l.strip() for l in ops.splitlines() if "APP_AUTO_START" in l]
        print("  %-42s %s" % (p, hit[0] if hit else "(未读到)"))


def list_apps():
    rows = app_rows()
    cfg = get(KEY_WHITELIST)
    allowed = (set(x.strip() for x in cfg.split(","))
               if cfg and cfg != "null" else set(BUILTIN_WHITELIST))
    print("=== 自装应用 (%d 个) ===" % len(rows))
    for p, comp in rows:
        mark = "可启动" if comp else "无启动入口(不能作为开机/唤醒目标)"
        inlist = "白名单" if p in allowed else "-"
        print("  %-42s %-16s %-8s %s" % (p, LABELS.get(p, "?"), mark, inlist))
        if comp:
            print("       -> %s" % comp)
    print("\n当前 %s = %r" % (KEY_WHITELIST, cfg))
    print("(显示 '-' 表示使用 APK 内置白名单时不在其中；写入自定义白名单后以实际值为准)")


def all_apps():
    rows = app_rows()
    pkgs = [p for p, comp in rows if comp and p != PKG]
    value = ",".join(pkgs)
    print("=== 把 %d 个可启动的自装应用写入白名单 ===" % len(pkgs))
    for p in pkgs:
        print("  ", describe(p))
    print("\n写入:", put(KEY_WHITELIST, value))
    print("回读长度:", len(get(KEY_WHITELIST)))
    print("\n撤销白名单: python boot_target.py --reset   (恢复 APK 内置白名单)")
    allow_autostart(pkgs)


def status():
    print("=== 开机自启配置 ===")
    t = get(KEY_TARGET)
    w = get(KEY_WHITELIST)
    print("  %s = %r  (未设置/空 = 内置默认 %s；off = 禁用)"
          % (KEY_TARGET, t, DEFAULT_TARGET))
    if w and w != "null":
        names = [x.strip() for x in w.split(",") if x.strip()]
        print("  %s = %d 个应用" % (KEY_WHITELIST, len(names)))
        for p in names:
            print("      -", describe(p))
    else:
        print("  %s = %r  (空 = APK 内置白名单)" % (KEY_WHITELIST, w))
    print("=== 唤醒静音（v3.5） ===")
    q = get(KEY_QUIET)
    if q and q.strip() in ("0", "off"):
        print("  %s = %r  => 已关闭：唤醒后保留 myDV 后台声音" % (KEY_QUIET, q))
    else:
        print("  %s = %r  => 默认开启：唤醒/开机进别的应用时清掉 myDV 后台音频"
              % (KEY_QUIET, q))
    print("=== 唤醒精确恢复界面（v3.6） ===")
    x = get(KEY_EXACT)
    if x and x.strip() in ("0", "off"):
        print("  %s = %r  => 已关闭：唤醒只用应用入口（回到旧行为）" % (KEY_EXACT, x))
    else:
        print("  %s = %r  => 默认开启：唤醒优先恢复待机前的那个界面" % (KEY_EXACT, x))
    print("=== 服务版本 / 绑定 ===")
    for line in sh("dumpsys", "package", PKG).splitlines():
        if "versionName=" in line or "versionCode=" in line:
            print(" ", line.strip()[:160])
    for line in sh("dumpsys", "accessibility").splitlines():
        if any(k in line for k in ("Bound services", "Enabled services",
                                   "Crashed services")):
            print(" ", line.strip()[:200])
    print("=== usage 授权 ===")
    ops = sh("cmd", "appops", "get", PKG)
    usage = [l.strip() for l in ops.splitlines() if "USAGE_STATS" in l]
    print(" ", usage if usage else "(未见 USAGE_STATS 显式项，以服务日志为准)")
    print("=== 服务记住的最近应用（日志） ===")
    log = sh("logcat", "-d", "-t", LOG_LINES, "-s", "MyDvResume:V")
    lasts = [l.strip() for l in log.splitlines()
             if "MyDvResume:" in l and "last=" in l]
    if lasts:
        print(" ", lasts[-1])
    else:
        print("  (本次开机后尚无新记录；开机目标从持久化记录 / 系统统计读取，")
        print("   详见 --boot-report 的 candidate / reason)")
    print("=== 当前前台 ===")
    print(" ", focus())


def wake_report():
    """Judge the most recent real standby -> wake with v3.6 exact restore."""
    log = sh("logcat", "-d", "-t", LOG_LINES, "-s", "MyDvResume:V")
    lines = [l.strip() for l in log.splitlines() if "MyDvResume:" in l]
    keys = ("SCREEN_OFF", "standby class", "WAKE via", "WAKE class",
            "exact resume blocked", "resumed exact class=",
            "skip repeat launch", "launched ", "launch failed")
    picked = [l for l in lines if any(k in l for k in keys)]
    print("=== 最近待机 -> 唤醒链路 (%d 行) ===" % len(picked))
    for l in picked[-40:]:
        print(" ", l)
    joined = "\n".join(picked)
    print("=== 判定 ===")
    off = "SCREEN_OFF" in joined
    cls = "standby class=" in joined
    wake = "WAKE via" in joined
    exact = "resumed exact class=" in joined
    blocked = "exact resume blocked" in joined
    print("  捕获待机广播     :", "YES" if off else "NO")
    print("  记下待机前界面   :", "YES" if cls else "NO")
    print("  捕获唤醒         :", "YES" if wake else "NO")
    print("  精确恢复成功     :", "YES" if exact else "NO")
    print("  精确恢复被拒回退 :", "YES" if blocked else "NO")
    print("  当前前台         :", focus())
    if off and wake and exact:
        print("  => 已按待机前的完整界面恢复")
    elif off and wake and blocked:
        print("  => 待机前界面已记录，但该 Activity 不导出(exported=false)，系统拒绝第三方拉起；")
        print("     已回退应用入口。若应用自己回收了播放页，只能用应用内「继续播放」。")
    elif not off or not wake:
        print("  => 这不是一次真实待机/唤醒；请用遥控器电源键待机再唤醒后重跑。")
    else:
        print("  => 见上方日志逐行定位")


def boot_report():
    log = sh("logcat", "-d", "-t", LOG_LINES, "-s", "MyDvResume:V")
    lines = [l.strip() for l in log.splitlines() if "MyDvResume:" in l]
    boot = [l for l in lines if "BOOT" in l or "bootId=" in l]
    print("=== 冷启动相关日志 (%d 行) ===" % len(boot))
    for l in boot[-30:]:
        print(" ", l)
    joined = "\n".join(boot)
    print("=== 判定 ===")
    detected = "BOOT detected" in joined
    launched = "BOOT launched" in joined
    cancelled = "BOOT cancelled" in joined
    done = "BOOT done" in joined
    print("  捕获冷启动 :", "YES" if detected else "NO")
    print("  拉起目标   :", "YES" if launched else "NO")
    print("  用户取消   :", "YES" if cancelled else "NO")
    print("  窗口汇总   :", "YES" if done else "NO")
    print("  当前前台   :", focus())
    if detected and launched and not cancelled:
        print("  => 冷启动自动拉起目标成功")
    elif not detected:
        print("  => 未捕获冷启动：检查服务开机是否自动重绑 / boot_id 是否可读")
    elif cancelled:
        print("  => 开机会话被用户主动操作取消（属预期保护）")
    else:
        print("  => 捕获到冷启动但未拉起，检查 BOOT launch failed / not launchable")


if __name__ == "__main__":
    if not connect():
        print("ADB 未连上电视（开机过程中请稍等，或先唤醒）")
        sys.exit(1)
    arg = sys.argv[1] if len(sys.argv) > 1 else "--status"
    if arg == "--set" and len(sys.argv) > 2:
        print("wb_boot_target =", put(KEY_TARGET, sys.argv[2]))
    elif arg == "--off":
        print("wb_boot_target =", put(KEY_TARGET, "off"), "(开机自启已禁用)")
    elif arg == "--on":
        print("wb_boot_target =", put(KEY_TARGET, DEFAULT_TARGET))
    elif arg == "--whitelist" and len(sys.argv) > 2:
        print("wb_boot_whitelist =", put(KEY_WHITELIST, sys.argv[2]))
    elif arg == "--list-apps":
        list_apps()
    elif arg == "--all-apps":
        all_apps()
    elif arg == "--allow-autostart":
        allow_autostart(current_whitelist())
    elif arg == "--quiet-off":
        print("wb_quiet_mydv =", put(KEY_QUIET, "0"),
              "(唤醒后保留 myDV 后台音频，回到旧行为)")
    elif arg == "--quiet-on":
        print("wb_quiet_mydv =", put(KEY_QUIET, "1"),
              "(唤醒/开机进别的应用时清掉 myDV 后台音频)")
    elif arg == "--exact-off":
        print("wb_exact_resume =", put(KEY_EXACT, "0"),
              "(唤醒只用应用入口，回到 v3.5 行为)")
    elif arg == "--exact-on":
        print("wb_exact_resume =", put(KEY_EXACT, "1"),
              "(唤醒优先恢复待机前的那个界面)")
    elif arg == "--wake-report":
        wake_report()
    elif arg == "--reset":
        for k in (KEY_TARGET, KEY_WHITELIST):
            sh("settings", "delete", "system", k)
            print(" ", k, "=", get(k))
    elif arg == "--boot-report":
        boot_report()
    else:
        status()
