#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stage the APK build into a pure-ASCII path (aapt2 cannot handle non-ASCII paths)."""
import os
import shutil

DST = r"C:\Temp\wbapk"
SRC = r"E:\WorkBuddy\闲聊\_tmp\apkbuild"
BT = r"E:\WorkBuddy\闲聊\_tmp\toolchain\bt\android-11"
AJAR = r"E:\WorkBuddy\闲聊\_tmp\toolchain\plat\android-11\android.jar"

if os.path.isdir(DST):
    shutil.rmtree(DST)
os.makedirs(DST, exist_ok=True)

for name in ("src", "res", "AndroidManifest.xml", "build_apk.py"):
    s = os.path.join(SRC, name)
    d = os.path.join(DST, name)
    if os.path.isdir(s):
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)

tool = os.path.join(DST, "tools")
os.makedirs(tool, exist_ok=True)
shutil.copytree(BT, tool, dirs_exist_ok=True)
shutil.copy2(AJAR, os.path.join(tool, "android.jar"))

# Rewrite path constants line by line (avoids fragile escaping of backslashes).
p = os.path.join(DST, "build_apk.py")
lines = open(p, encoding="utf-8").read().splitlines()
out = []
for line in lines:
    if line.startswith("ROOT = "):
        line = 'ROOT = r"C:\\Temp\\wbapk"'
    elif line.startswith("BT = "):
        line = 'BT = r"C:\\Temp\\wbapk\\tools"'
    elif line.startswith("ANDROID_JAR = "):
        line = 'ANDROID_JAR = r"C:\\Temp\\wbapk\\tools\\android.jar"'
    out.append(line)
open(p, "w", encoding="utf-8").write("\n".join(out) + "\n")

print("staged to", DST)
print("tools files", len(os.listdir(tool)))
for l in out:
    if l.startswith(("ROOT =", "BT =", "ANDROID_JAR =", "JBR =")):
        print("  ", l)
