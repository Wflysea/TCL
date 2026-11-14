# -*- coding: utf-8 -*-
"""
TCL 75V8L-C3 (tc8000_ay30a2) 精简还原脚本

用法:
  python restore_tcl.py --status    查看当前禁用包数与屏保设置
  python restore_tcl.py --this      只撤销本次改动（启用本次新增的 3 个包，屏保保持修正后的值）
  python restore_tcl.py --all       完全还原精简：启用精简后记录的 27 个包，并把两个屏保键恢复为改动前原值

注意:
  - 本脚本只管「精简 + 屏保」。后续「待机续播加固」（deviceidle 白名单、
    APP_AUTO_START 授权）以及额外禁用的厂商应用（com.tcl.guard、
    com.tcl.appmarket2 等）由 check_standby_resume.py --unharden 统一撤销；
    --all 不会重新启用它们。

前提:
  - 电视开机、网络 ADB 调试开启、IP 仍为 192.168.1.26
  - 首次连接可能需要在电视上确认「允许 USB 调试」
  - 所有操作都是 pm enable，不会卸载任何应用
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
DEV = "192.168.1.26:5555"
OLD_SCREENSAVER = "com.tcl.appreciate.art/.service.screensaver.ScreenSaverBootService"
NEW_SCREENSAVER = "com.android.dreams.basic/.Colors"
NEW_PKGS = [
    "android.autoinstalls.config.tcl.device",
    "com.audiocn.karaoke.micmanager",
    "com.tcl.common.weather",
]


def shell(*args):
    r = subprocess.run(
        [ADB, "-s", DEV, "shell", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return (r.stdout or "").strip()


def read_disabled(fname):
    result = []
    with open(os.path.join(HERE, fname), encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip().replace("\r", "")
            if line.startswith("package:"):
                result.append(line[len("package:"):])
    return result


def count_disabled():
    return len([l for l in shell("pm", "list", "packages", "-d").splitlines()
                if l.startswith("package:")])


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--status"
    if not os.path.isfile(ADB):
        print("找不到 adb:", ADB)
        return 1
    subprocess.run([ADB, "connect", DEV], capture_output=True, text=True)

    if mode == "--status":
        print("当前禁用包数:", count_disabled())
        print("屏保 components =", shell("settings", "get", "secure", "screensaver_components"))
        print("屏保 default    =", shell("settings", "get", "secure", "screensaver_default_component"))
        print("记录: 改动前 %d 个 / 精简后 %d 个（之后另由 check_standby_resume.py 禁用了若干厂商应用，数量会更多）" % (
            len(read_disabled("packages_disabled_before.txt")),
            len(read_disabled("packages_disabled_after.txt")),
        ))
        print("提示: 撤销加固与厂商应用禁用请用 python check_standby_resume.py --unharden")
        subprocess.run([ADB, "disconnect", DEV], capture_output=True)
        return 0

    if mode == "--this":
        pkgs = NEW_PKGS
    elif mode == "--all":
        pkgs = read_disabled("packages_disabled_after.txt")
    else:
        print("未知参数:", mode)
        return 1

    print("将启用 %d 个包..." % len(pkgs))
    for p in pkgs:
        print("  %-48s %s" % (p, shell("pm", "enable", p)))
    if mode == "--all":
        for key in ("screensaver_components", "screensaver_default_component"):
            shell("settings", "put", "secure", key, OLD_SCREENSAVER)
        print("屏保现值:", shell("settings", "get", "secure", "screensaver_components"),
              "/", shell("settings", "get", "secure", "screensaver_default_component"))
    print("剩余禁用包数:", count_disabled())
    subprocess.run([ADB, "disconnect", DEV], capture_output=True)
    print("完成。建议重启电视一次让状态落盘（pm 写入有约 10 秒延迟）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
