#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Build the tiny myDV wake-resume APK using only locally available tools.

No Gradle / Android Studio project needed:
  aapt2 (compile + link) -> javac -> dx -> zipalign -> keytool -> apksigner

NOTE: this file is published in a PUBLIC repository. The signing keystore
(mydvresume.jks) and its password are intentionally NOT included. See
apk/README.md for how to recreate them locally.
"""
import os
import re
import shutil
import subprocess
import zipfile

ROOT = r"C:\Temp\wbapk"
JBR = r"C:\Program Files\JetBrains\PyCharm 2026.2.3\jbr"
BT = r"C:\Temp\wbapk\tools"
ANDROID_JAR = r"C:\Temp\wbapk\tools\android.jar"

JAVA = os.path.join(JBR, "bin", "java.exe")
JAVAC = os.path.join(JBR, "bin", "javac.exe")
KEYTOOL = os.path.join(JBR, "bin", "keytool.exe")
AAPT2 = os.path.join(BT, "aapt2.exe")
ZIPALIGN = os.path.join(BT, "zipalign.exe")
D8_JAR = os.path.join(BT, "lib", "d8.jar")
DX_JAR = os.path.join(BT, "lib", "dx.jar")
APKSIGNER_JAR = os.path.join(BT, "lib", "apksigner.jar")

SRC = os.path.join(ROOT, "src", "com", "wb", "mydvresume", "ResumeService.java")
CLASSES = os.path.join(ROOT, "classes")
DEXOUT = os.path.join(ROOT, "dexout")
RES = os.path.join(ROOT, "res")
MANIFEST = os.path.join(ROOT, "AndroidManifest.xml")

RES_ZIP = os.path.join(ROOT, "compiled_res.zip")
BASE_APK = os.path.join(ROOT, "base.apk")
ALIGNED_APK = os.path.join(ROOT, "aligned.apk")
FINAL_APK = os.path.join(ROOT, "MyDvResume.apk")
KEYSTORE = os.path.join(ROOT, "mydvresume.jks")


def load_keystore_password():
    """Read the signing password from a local, gitignored file or env var.

    Order: MYDV_KEYSTORE_PASS_FILE -> ROOT/.keystore_pass ->
           MYDV_KEYSTORE_PASSWORD environment variable.
    """
    p = os.environ.get("MYDV_KEYSTORE_PASS_FILE") or os.path.join(ROOT, ".keystore_pass")
    if os.path.isfile(p):
        with open(p, "r", encoding="utf-8") as f:
            pw = f.read().strip()
        if pw:
            return pw
    pw = os.environ.get("MYDV_KEYSTORE_PASSWORD", "").strip()
    if pw:
        return pw
    raise RuntimeError(
        "keystore password missing: create C:\\Temp\\wbapk\\.keystore_pass "
        "(single line) or set MYDV_KEYSTORE_PASSWORD")


PASSWORD = load_keystore_password()


def redact(text):
    """Never echo the keystore password into build logs / CI output."""
    return re.sub(r"(pass:)[^\s\"]+", r"\1<REDACTED>", text)


def run(label, cmd, cwd=None):
    print("=== %s ===" % label, flush=True)
    shown = " ".join('"%s"' % c if " " in c else c for c in cmd)
    print("   ", redact(shown), flush=True)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=300)
    out = redact((p.stdout + p.stderr).decode("utf-8", "replace"))
    if out.strip():
        for line in out.strip().splitlines()[:25]:
            print("   ", line, flush=True)
    if p.returncode != 0:
        raise RuntimeError("%s failed (exit %d)" % (label, p.returncode))
    print("    OK", flush=True)


def main():
    for d in (CLASSES, DEXOUT):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)

    # 1. compile resources
    if os.path.isfile(RES_ZIP):
        os.remove(RES_ZIP)
    run("aapt2 compile", [AAPT2, "compile", "--dir", RES, "-o", RES_ZIP])

    # 2. link -> APK with binary AndroidManifest.xml + resources.arsc
    for p in (BASE_APK, ALIGNED_APK, FINAL_APK):
        if os.path.isfile(p):
            os.remove(p)
    run("aapt2 link", [AAPT2, "link",
                       "-o", BASE_APK,
                       "-I", ANDROID_JAR,
                       "--manifest", MANIFEST,
                       "--min-sdk-version", "21",
                       "--target-sdk-version", "30",
                       "--auto-add-overlay",
                       RES_ZIP])

    # 3. javac (release 8 -> class version 52, required by the old dx tool;
    #    D8 2.1.7 crashes with an NPE on JDK 25, so we use dx instead)
    run("javac", [JAVAC, "--release", "8", "-encoding", "UTF-8",
                  "-cp", ANDROID_JAR, "-d", CLASSES, SRC])

    class_files = []
    for base, _, files in os.walk(CLASSES):
        for f in files:
            if f.endswith(".class"):
                class_files.append(os.path.join(base, f))
    print("    class files:", [os.path.basename(x) for x in class_files], flush=True)

    # 4. dx -> classes.dex
    dex = os.path.join(DEXOUT, "classes.dex")
    if os.path.isfile(dex):
        os.remove(dex)
    run("dx", [JAVA, "-cp", DX_JAR, "com.android.dx.command.Main",
               "--dex", "--output=" + dex, CLASSES])
    if not os.path.isfile(dex):
        raise RuntimeError("classes.dex not produced")

    # 5. add classes.dex into the linked APK
    with zipfile.ZipFile(BASE_APK, "a", zipfile.ZIP_DEFLATED) as z:
        z.write(dex, "classes.dex")
    print("=== add classes.dex ===\n    OK (%d bytes)" % os.path.getsize(dex), flush=True)

    # 6. zipalign
    run("zipalign", [ZIPALIGN, "-f", "4", BASE_APK, ALIGNED_APK])

    # 7. keystore (idempotent). Never commit the .jks file.
    if not os.path.isfile(KEYSTORE):
        run("keytool", [KEYTOOL, "-genkeypair", "-alias", "mydv",
                        "-keyalg", "RSA", "-keysize", "2048",
                        "-validity", "10000",
                        "-keystore", KEYSTORE,
                        "-storepass", PASSWORD, "-keypass", PASSWORD,
                        "-dname", "CN=myDV Resume, OU=Local, O=Local, L=Local, ST=Local, C=CN"])

    # 8. sign (V1 + V2; apksigner also emits V3 when applicable)
    run("apksigner sign", [JAVA, "-cp", APKSIGNER_JAR,
                           "com.android.apksigner.ApkSignerTool", "sign",
                           "--ks", KEYSTORE,
                           "--ks-pass", "pass:" + PASSWORD,
                           "--key-pass", "pass:" + PASSWORD,
                           "--min-sdk-version", "21",
                           "--v1-signing-enabled", "true",
                           "--v2-signing-enabled", "true",
                           "--out", FINAL_APK, ALIGNED_APK])

    # 9. verify
    run("apksigner verify", [JAVA, "-cp", APKSIGNER_JAR,
                             "com.android.apksigner.ApkSignerTool", "verify",
                             "--verbose", FINAL_APK])

    with zipfile.ZipFile(FINAL_APK) as z:
        print("=== final APK ===")
        print("    size:", os.path.getsize(FINAL_APK), "bytes")
        print("    entries:", z.namelist())
    print("BUILD OK ->", FINAL_APK, flush=True)


if __name__ == "__main__":
    main()
