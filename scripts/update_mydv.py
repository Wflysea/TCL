#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""myDV (com.github.mytv.dv) 升级助手 —— 仅用 Python 标准库。

用法:
  python update_mydv.py --check              # 只读：查上游最新版 + 电视当前版，不做任何改动
  python update_mydv.py --upgrade           # 有新版时下载并用 adb install -r 覆盖安装（保留数据）
  python update_mydv.py --install-local X.apk  # 用本机已有 APK 覆盖安装

说明:
  * 覆盖安装用 install -r，不会卸载、不会丢收藏/历史；若报签名不兼容，脚本不会自动卸载。
  * 上游: https://github.com/mytv-android/myDV  (应用内也是查 releases/latest)
  * 下载优先走 api.github.com 的 asset 接口；失败时依次尝试 GitHub 直连与公共镜像。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

REPO = "mytv-android/myDV"
PKG = "com.github.mytv.dv"
DEVICE = "192.168.1.26:5555"
ADB = r"E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe"
CACHE_DIR = r"E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup\mydv_updates"
UA = {"User-Agent": "workbuddy", "Accept": "application/vnd.github+json"}


def run(*args, timeout=90):
    p = subprocess.run(list(args), capture_output=True, timeout=timeout)
    out = (p.stdout + p.stderr).decode("utf-8", "replace").replace("\r", "")
    return p.returncode, out.strip()


def adb(*args, timeout=180):
    return run(ADB, "-s", DEVICE, *args, timeout=timeout)


def adb_connect():
    run(ADB, "connect", DEVICE, timeout=30)
    _, out = run(ADB, "devices", timeout=30)
    line = next((l for l in out.splitlines() if DEVICE in l), "")
    if "device" not in line or "unauthorized" in line or "offline" in line:
        raise RuntimeError("电视未授权或不可达: %r\n%s" % (line, out))
    return True


def installed_version():
    _, out = adb("shell", "dumpsys", "package", PKG)
    name = re.search(r"versionName=([^\s]+)", out)
    code = re.search(r"versionCode=(\d+)", out)
    if not name:
        raise RuntimeError("读不到 %s 的版本，确认应用是否已安装" % PKG)
    return name.group(1), int(code.group(1)) if code else None


def vtuple(s):
    nums = [int(x) for x in re.findall(r"\d+", s or "")]
    return tuple((nums + [0, 0, 0])[:3])


def latest_release():
    url = "https://api.github.com/repos/%s/releases/latest" % REPO
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
        d = json.load(r)
    apks = [a for a in d.get("assets", []) if a["name"].lower().endswith(".apk")]
    if not apks:
        raise RuntimeError("最新 release 里没有 APK 资产")
    return {
        "tag": d.get("tag_name", ""),
        "name": d.get("name", ""),
        "published": d.get("published_at", ""),
        "notes": (d.get("body") or "").strip(),
        "asset": apks[0],
    }


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(asset):
    os.makedirs(CACHE_DIR, exist_ok=True)
    dest = os.path.join(CACHE_DIR, asset["name"])
    size = asset["size"]
    candidates = [
        ("api-asset", asset["url"], {"User-Agent": "workbuddy", "Accept": "application/octet-stream"}),
        ("github", asset["browser_download_url"], {"User-Agent": "workbuddy"}),
    ]
    for prefix in ("https://ghproxy.net/", "https://mirror.ghproxy.com/", "https://gh-proxy.com/"):
        candidates.append((prefix.rstrip("/"), prefix + asset["browser_download_url"], {"User-Agent": "workbuddy"}))

    for label, url, hdr in candidates:
        try:
            print("  下载通道: %s" % label, flush=True)
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60) as r, open(dest, "wb") as f:
                got = 0
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if got % (2 << 20) < 65536:
                        print("    %.1f / %.1f MB" % (got / 1048576, size / 1048576), flush=True)
            if got != size:
                print("    大小不符 (%d != %d)，换下一个通道" % (got, size), flush=True)
                continue
            if not zipfile.is_zipfile(dest):
                print("    不是有效 APK，换下一个通道", flush=True)
                continue
            print("  下载完成: %s  sha256=%s" % (dest, sha256(dest)), flush=True)
            return dest
        except Exception as e:
            print("    失败: %s %s" % (type(e).__name__, str(e)[:100]), flush=True)
    raise RuntimeError("所有下载通道都失败，可手动从 https://github.com/%s/releases 下载后用 --install-local" % REPO)


def install(apk):
    # adb install 对含中文的路径偶有问题，先复制到纯 ASCII 临时目录
    tmp = os.path.join(tempfile.gettempdir(), "mydv_update.apk")
    shutil.copy2(apk, tmp)
    print("  安装: adb install -r %s" % tmp, flush=True)
    code, out = adb("install", "-r", tmp, timeout=420)
    print("  " + out.replace("\n", "\n  "), flush=True)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if "Success" not in out:
        if "UPDATE_INCOMPATIBLE" in out or "signatures" in out.lower():
            raise RuntimeError("签名不一致，覆盖安装被拒。脚本不会自动卸载（会丢数据）。\n"
                               "如确认来源可靠，需手动 adb uninstall %s 再安装。" % PKG)
        raise RuntimeError("安装失败，电视未被改动")
    return True


def check_only():
    print("连接电视 ...", flush=True)
    adb_connect()
    cur, code = installed_version()
    rel = latest_release()
    print("  电视当前 : %s (versionCode=%s)" % (cur, code))
    print("  上游最新 : %s  %s" % (rel["tag"], rel["name"]))
    print("  发布时间 : %s" % rel["published"])
    print("  APK      : %s  %d 字节" % (rel["asset"]["name"], rel["asset"]["size"]))
    if rel["notes"]:
        print("  更新内容 : %s" % rel["notes"].replace("\n", " ")[:300])
    a, b = vtuple(cur), vtuple(rel["tag"])
    if a == b:
        print("\n结论: 已是最新版，无需升级。")
        return 0
    if a > b:
        print("\n结论: 电视上的版本比上游最新 release 还新（可能是内测/预发布包），不建议降级。")
        return 0
    print("\n结论: 有新版本可用，执行 python update_mydv.py --upgrade 升级。")
    return 1


def main():
    ap = argparse.ArgumentParser(description="myDV 升级助手")
    ap.add_argument("--check", action="store_true", help="只读检查版本")
    ap.add_argument("--upgrade", action="store_true", help="下载最新版并覆盖安装")
    ap.add_argument("--install-local", metavar="APK", help="用本机 APK 覆盖安装")
    args = ap.parse_args()
    if not (args.check or args.upgrade or args.install_local):
        ap.print_help()
        return 2
    try:
        if args.check:
            return check_only()
        adb_connect()
        before, code = installed_version()
        print("升级前版本: %s (versionCode=%s)" % (before, code), flush=True)
        if args.install_local:
            apk = args.install_local
            if not os.path.isfile(apk) or not zipfile.is_zipfile(apk):
                raise RuntimeError("不是有效的 APK 文件: %s" % apk)
            print("  本地 APK: %s  sha256=%s" % (apk, sha256(apk)), flush=True)
        else:
            rel = latest_release()
            a, b = vtuple(before), vtuple(rel["tag"])
            if a >= b:
                print("已是最新版 %s，无需升级。" % rel["tag"], flush=True)
                return 0
            print("发现新版本 %s (当前 %s)" % (rel["tag"], before), flush=True)
            apk = download(rel["asset"])
        install(apk)
        after, code2 = installed_version()
        print("升级后版本: %s (versionCode=%s)" % (after, code2), flush=True)
        print("完成。" if after != before else "警告: 版本号未变化，请检查安装输出。", flush=True)
        return 0
    except Exception as e:
        print("错误: %s" % e, file=sys.stderr, flush=True)
        return 1
    finally:
        run(ADB, "disconnect", DEVICE, timeout=15)


if __name__ == "__main__":
    sys.exit(main())
