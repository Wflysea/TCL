#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Sync every local change of the TCL / myDV Resume project into this repo,
then commit and push to GitHub over SSH.

This is the "push on every change" entry point. Run it after ANY edit to the
source, the ops scripts or the docs:

    python scripts/sync_and_push.py
    python scripts/sync_and_push.py --message "v4.2 auto-learning whitelist"
    python scripts/sync_and_push.py --no-push      # sync + commit only
    python scripts/sync_and_push.py --dry-run      # report, change nothing

Local working copies live OUTSIDE the repo (the build toolchain needs fixed
absolute paths):
    C:\\Temp\\wbapk                              APK sources + build output
    E:\\WorkBuddy\\闲聊\\_tmp\\tcl75v8l_backup     ops / diagnostic scripts

Credentials are NEVER copied here: the .jks keystore, .keystore_pass, GitHub
tokens, the pulled third-party APK and the big dexdump intermediates are all
excluded by .gitignore and by the whitelist below.
"""
from __future__ import print_function

import argparse
import datetime
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APK_SRC = r"C:\Temp\wbapk"
OPS_SRC = r"E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup"
INITIAL_SRC = os.path.join(OPS_SRC, "apk_source")

TEXT_SNAPSHOT_EXT = (".txt", ".json", ".log")
SANITIZE_FILES = ("getprop.txt", "config_all.txt",
                  "settings_secure_all.txt", "settings_system_all.txt")


def log(msg):
    print("[sync] " + msg, flush=True)


def scrub(text):
    """Remove device identifiers / credentials from raw system dumps."""
    text = re.sub(r"(\[ro\.(?:boot\.)?serialno\]: \[)[^\]]*(\])",
                  r"\1<REDACTED>\2", text)
    text = re.sub(r"ghp_[A-Za-z0-9]{20,}", "<REDACTED_GITHUB_TOKEN>", text)
    text = re.sub(r"github_pat_[A-Za-z0-9_]{20,}", "<REDACTED_GITHUB_TOKEN>", text)
    text = re.sub(r"(?i)(speak_password|childPwd)\s*=\s*[^\r\n,]*",
                  r"\1=<REDACTED>", text)
    return text


def rel(*parts):
    return os.path.join(REPO, *[p.replace("/", os.sep) for p in parts])


def copy_file(src, dst, sanitize=False, dry_run=False):
    if not os.path.isfile(src):
        log("SKIP (missing locally): " + src)
        return False
    data = open(src, "rb").read()
    if sanitize:
        data = scrub(data.decode("utf-8", "replace")).encode("utf-8")
    short = os.path.relpath(dst, REPO)
    if os.path.isfile(dst) and open(dst, "rb").read() == data:
        return False
    if dry_run:
        log("WOULD UPDATE " + short)
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as f:
        f.write(data)
    log("updated " + short)
    return True


def git(*args, **kwargs):
    check = kwargs.pop("check", True)
    silent = kwargs.pop("silent", False)
    cmd = ["git", "-C", REPO] + list(args)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, encoding="utf-8", errors="replace")
    out = (p.stdout or "").strip()
    if out and not silent:
        for line in out.splitlines():
            print("    " + line, flush=True)
    if check and p.returncode != 0:
        raise RuntimeError("git %s failed (exit %d)" % (args[0], p.returncode))
    return p.returncode, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--message", "-m", help="custom commit message")
    ap.add_argument("--no-push", action="store_true", help="sync + commit only")
    ap.add_argument("--dry-run", action="store_true", help="report changes only")
    args = ap.parse_args()

    changed = 0

    # ---- 1. current APK sources -------------------------------------------
    for src_name, dst in (
        ("AndroidManifest.xml", "apk/AndroidManifest.xml"),
        ("src/com/wb/mydvresume/ResumeService.java",
         "apk/src/com/wb/mydvresume/ResumeService.java"),
        ("res/values/strings.xml", "apk/res/values/strings.xml"),
        ("res/xml/resume_config.xml", "apk/res/xml/resume_config.xml"),
        ("build_apk.py", "apk/build_apk.py"),
    ):
        changed += copy_file(os.path.join(APK_SRC, src_name.replace("/", os.sep)),
                             rel(dst), dry_run=args.dry_run)

    # ---- 2. signed release APK, one file per versionCode ------------------
    manifest = os.path.join(APK_SRC, "AndroidManifest.xml")
    vc = "unknown"
    if os.path.isfile(manifest):
        m = re.search(r'android:versionCode="(\d+)"',
                      open(manifest, encoding="utf-8", errors="replace").read())
        if m:
            vc = m.group(1)
    apk_out = rel("releases", "MyDvResume-vc%s.apk" % vc)
    changed += copy_file(os.path.join(APK_SRC, "MyDvResume.apk"), apk_out,
                         dry_run=args.dry_run)

    # ---- 3. historical source snapshots ----------------------------------
    history = {
        "v36_ResumeService.java": "history/v3.6/ResumeService.java",
        "v310_ResumeService.java": "history/v3.10/ResumeService.java",
        "v310_AndroidManifest.xml": "history/v3.10/AndroidManifest.xml",
        "v391_ResumeService.java": "history/v3.9.1/ResumeService.java",
        "v391_AndroidManifest.xml": "history/v3.9.1/AndroidManifest.xml",
        "v40_ResumeService.java": "history/v4.0/ResumeService.java",
        "v40_AndroidManifest.xml": "history/v4.0/AndroidManifest.xml",
        "v41_ResumeService.java": "history/v4.1/ResumeService.java",
        "v41_AndroidManifest.xml": "history/v4.1/AndroidManifest.xml",
        "v421_ResumeService.java": "history/v4.2.1/ResumeService.java",
        "v421_AndroidManifest.xml": "history/v4.2.1/AndroidManifest.xml",
        "v43_ResumeService.java": "history/v4.3/ResumeService.java",
        "v43_AndroidManifest.xml": "history/v4.3/AndroidManifest.xml",
    }
    for name, dst in sorted(history.items()):
        changed += copy_file(os.path.join(APK_SRC, name), rel(dst),
                             dry_run=args.dry_run)

    # Initial (v1) snapshot. build_apk.py in apk_source contains a plaintext
    # legacy password, so only manifest + resources are copied.
    for name in ("AndroidManifest.xml", "res/values/strings.xml",
                 "res/xml/resume_config.xml"):
        changed += copy_file(os.path.join(INITIAL_SRC, name.replace("/", os.sep)),
                             rel("history/v1-initial", name), dry_run=args.dry_run)
    changed += copy_file(os.path.join(OPS_SRC, "MyDvResume.apk"),
                         rel("history/v1-initial", "MyDvResume-v1.apk"),
                         dry_run=args.dry_run)

    # ---- 4. all ops / diagnostic scripts ----------------------------------
    for name in sorted(os.listdir(OPS_SRC)):
        src = os.path.join(OPS_SRC, name)
        if not os.path.isfile(src):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext == ".py":
            changed += copy_file(src, rel("scripts", name), dry_run=args.dry_run)
        elif ext in TEXT_SNAPSHOT_EXT:
            changed += copy_file(src, rel("device-backup", name),
                                 sanitize=(name in SANITIZE_FILES),
                                 dry_run=args.dry_run)

    if args.dry_run:
        log("dry run done: %d file(s) would change" % changed)
        return 0

    # ---- 5. commit + push --------------------------------------------------
    git("symbolic-ref", "HEAD", "refs/heads/main", check=False)
    git("add", "-A")
    rc, _ = git("diff", "--cached", "--quiet", check=False)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if rc == 0:
        log("no file changes to commit")
    else:
        _, names = git("diff", "--cached", "--name-only", check=False, silent=True)
        real_changed = len([x for x in names.splitlines() if x.strip()])
        msg = args.message or ("sync: %s | vc%s | %d file(s) changed"
                               % (stamp, vc, real_changed))
        git("-c", "user.name=Wflysea",
            "-c", "user.email=Wflysea@users.noreply.github.com",
            "commit", "-m", msg)
        log("committed: " + msg)

    if args.no_push:
        log("--no-push: skipping push")
        return 0
    git("push", "-u", "origin", "main")
    log("pushed to Wflysea/TCL @ main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
