# -*- coding: utf-8 -*-
"""TCL 75V8L-C3 远程操控面：只读审计，不修改电视任何设置。"""
import subprocess

ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
DEV = "192.168.1.26:5555"

GROUPS = [
    ("OTA / 固件推送", ["com.tcl.versionUpdateApp", "com.tcl.ttvs", "com.snm.upgrade", "com.tcl.UpdatePeripheral"]),
    ("推送 / 静默安装 / 应用分发", ["com.tcl.c2dm.client", "android.autoinstalls.config.tcl.device", "com.tcl.appmarket2", "com.tcl.guard"]),
    ("遥测 / 内容识别 / 账号", ["com.tcl.logkit", "com.tcl.bi", "com.tcl.recognize.service", "com.tcl.profilemanager", "com.tcl.usercenter"]),
    ("语音 / 麦克风 / 无障碍", ["com.tcl.walleve", "com.tcl.micmanager", "com.tcl.hearaid", "com.tcl.soundbox"]),
    ("局域网控制 / 投屏", ["com.tcl.miracast", "com.tcl.MultiScreenInteraction_TV", "com.tcl.autopair", "com.tcl.tcl_bt_rcu_service"]),
    ("系统常驻服务 / 桌面", ["com.tcl.systemserver", "com.tcl.TFDS.service", "com.tcl.xian.StartandroidService", "com.tcl.tv", "com.tcl.cyberui"]),
]


def sh(*args, timeout=25):
    try:
        r = subprocess.run([ADB, "-s", DEV, "shell", *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return (r.stdout or "").strip()
    except Exception as e:
        return "ERR: %s" % e


def pkg_state(p, all_set, off):
    if p not in all_set:
        return "不存在"
    return "已禁用" if p in off else "【启用】"


def listening_ports():
    raw = sh("cat", "/proc/net/tcp") + "\n" + sh("cat", "/proc/net/tcp6")
    ports = set()
    for line in raw.splitlines():
        f = line.split()
        if len(f) > 3 and f[3] == "0A" and ":" in f[1]:
            try:
                ports.add(int(f[1].split(":")[1], 16))
            except ValueError:
                pass
    return sorted(ports)


def main():
    subprocess.run([ADB, "connect", DEV], capture_output=True, timeout=20)
    print("设备:", sh("getprop", "ro.build.display.id"))
    print()

    allp = [l.strip()[len("package:"):] for l in sh("pm", "list", "packages").splitlines()
            if l.strip().startswith("package:")]
    all_set = set(allp)
    off = {l.strip()[len("package:"):] for l in sh("pm", "list", "packages", "-d").splitlines()
           if l.strip().startswith("package:")}
    print("包总数 %d，已禁用 %d" % (len(allp), len(off)))
    print()

    print("=== 远程相关组件状态 ===")
    for name, pkgs in GROUPS:
        print("[%s]" % name)
        for p in pkgs:
            print("   %-46s %s" % (p, pkg_state(p, all_set, off)))
    print()

    print("=== 特权应用（/system/priv-app，用户无法卸载）中与远控相关的 ===")
    paths = sh("pm", "list", "packages", "-f")
    keys = ("update", "upgrade", "push", "c2dm", "install", "guard", "market",
            "systemserver", "remote", "assist", "voice", "walleve", "miracast", "multiscreen")
    n = 0
    for line in paths.splitlines():
        low = line.lower()
        if "/system/priv-app/" in low and any(k in low for k in keys):
            print("   ", line.strip())
            n += 1
    print("   合计 %d 个" % n)
    print()

    print("=== 设备管理器 / 设备所有者 ===")
    dp = sh("dumpsys", "device_policy")
    hit = [l.strip() for l in dp.splitlines()
           if any(k in l.lower() for k in ("device owner", "admin", "active"))][:12]
    print("\n".join("   " + l for l in hit) if hit else "   未发现已激活的设备管理器")
    print()

    print("=== 无障碍服务（可被用来模拟按键 / 读屏） ===")
    print("   enabled_accessibility_services =", sh("settings", "get", "secure", "enabled_accessibility_services"))
    print("   accessibility_enabled =", sh("settings", "get", "secure", "accessibility_enabled"))
    print()

    print("=== 已登录账号 ===")
    acc = [l.strip() for l in sh("dumpsys", "account").splitlines() if "Account{" in l][:10]
    print("\n".join("   " + l for l in acc) if acc else "   无账号记录")
    print()

    print("=== 监听中的 TCP 端口 ===")
    print("   ", listening_ports())
    print()

    print("=== 网络 ADB 开关 ===")
    print("   adb tcpip / 服务端口 5555:", "开放" if 5555 in listening_ports() else "未监听")
    print("   getprop service.adb.tcp.port =", sh("getprop", "service.adb.tcp.port") or "(未设置)")

    subprocess.run([ADB, "disconnect", DEV], capture_output=True)
    print("\n审计结束，未修改任何设置。")


if __name__ == "__main__":
    main()
