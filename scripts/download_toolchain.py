#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""下载编译 APK 所需工具链（纯标准库，带进度与断点式跳过）。"""
import os
import time
import urllib.request

OUT = r"E:\WorkBuddy\闲聊\_tmp\toolchain"
os.makedirs(OUT, exist_ok=True)

URLS = [
    ("platform-30.zip", "https://dl.google.com/android/repository/platform-30_r03.zip", 52_328_361),
    ("jdk17.zip", "https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.zip", 187_236_595),
]


def main():
    for name, url, expect in URLS:
        path = os.path.join(OUT, name)
        if os.path.isfile(path) and os.path.getsize(path) >= expect * 0.98:
            print("SKIP %s (%.1f MB)" % (name, os.path.getsize(path) / 1048576), flush=True)
            continue
        print("DOWNLOAD %s" % name, flush=True)
        req = urllib.request.Request(url, headers={"User-Agent": "workbuddy"})
        with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
            n = 0
            start = time.time()
            last = 0
            while True:
                b = r.read(262144)
                if not b:
                    break
                f.write(b)
                n += len(b)
                if n - last >= 20 * 1048576:
                    last = n
                    print("  %.1f MB  %.0f KB/s" % (n / 1048576, n / 1024 / max(time.time() - start, 1)), flush=True)
        size = os.path.getsize(path)
        print("DONE %s %.1f MB (expect %.1f MB) %s" %
              (name, size / 1048576, expect / 1048576, "OK" if size >= expect * 0.98 else "INCOMPLETE"),
              flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
