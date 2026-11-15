# 构建 → 推送 → 重绑 → 验证

一次版本发布的固定流程。所有脚本都在 `scripts/`（本机工作副本在 `E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup`）。

## 0. 环境（本机固定路径）

| 项 | 路径 |
| --- | --- |
| ADB | `E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe` |
| APK 源码 / 构建输出 | `C:\Temp\wbapk`（纯 ASCII，避免 aapt2 中文路径问题） |
| 构建工具链 | `C:\Temp\wbapk\tools`（aapt2 / dx / zipalign / apksigner / android.jar） |
| JDK | `C:\Program Files\JetBrains\PyCharm 2026.2.3\jbr` |
| 设备 | `192.168.1.26:5555` |

> 本机 adb daemon 在每次终端调用之间会重启，`adb -s ... shell` 可能报 `device not found`；把 `adb connect` 和后续检查放在**同一条命令**里。

## 1. 升版本号（覆盖安装必须递增）

两处必须同步：

- `C:\Temp\wbapk\AndroidManifest.xml` → `android:versionCode` / `android:versionName`
- `scripts/push_apk.py` → `VERSION`（多屏互动安装协议里带上版本）

再改源码（`ResumeService.java`）和日志标记 `service connected vX.Y`，方便从 logcat 判断设备上跑的是哪一版。

## 2. 构建与签名

```bash
cd C:\Temp\wbapk
python build_apk.py
```

校验（三步都做）：

```bash
./tools/aapt.exe dump badging MyDvResume.apk | head -4        # 版本号
./tools/aapt.exe dump badging MyDvResume.apk | grep -Ei "home|launcher|queries"  # 必须为空
sha256sum MyDvResume.apk                                     # 记录指纹
```

`build_apk.py` 末尾会跑 `apksigner verify --verbose`，应看到 V1/V2/V3 全部通过。口令从 `C:\Temp\wbapk\.keystore_pass` 读取，**不要**把它写回脚本或提交到仓库。

## 3. 推送安装

```bash
cd E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup
python push_apk.py
```

- 走 **6553 tcast / `com.tcl.MultiScreenInteraction_TV`** 多屏互动，不是 `adb install`。
- **电视端会弹安装确认：按「右」选中「同意」再按确认。**
- 成功标志：`stage=5 INSTALLED`。出现过 `stage=2` 重试提示只是多 URL 兜底，不代表失败；以 `INSTALLED` 和设备实际版本为准。
- 2026-11-15 起，收到 `INSTALLED` 后脚本会打印 `keeping session alive for TV teardown (<= 10s)...` 并**多等最多 10 秒**：这段时间继续发 `150>>` 心跳、HTTP server 继续提供 APK，让电视端把 `onBusinessRemove` 收尾走完或主动关闭会话。这是**刻意行为**，不是卡住。原因见 [troubleshooting.md](troubleshooting.md) 的「安装成功瞬间闪出下载失败」。
- 若电视端主动关闭会话，会打印 `TV closed the session cleanly` 并立刻退出；否则等满 `GRACE_SECONDS`（默认 10 秒）再优雅关闭。优雅期内收到的后续 `223` 状态会打印成 `late TV state:`，便于诊断。
- 若遇到残留的旧安装通知或模型侧报错，先核查 `dumpsys package com.wb.mydvresume | grep versionCode` 与设备内 `base.apk` 哈希，别急着重推。

设备内哈希核对：

```bash
adb shell "sha256sum $(pm path com.wb.mydvresume | sed 's/package://')"
```

## 4. 重绑（每次覆盖安装后必做）

```bash
python finalize_resume.py
```

它会：

- toggle `enabled_accessibility_services` 触发系统重新绑定服务（只写 settings 不重绑会出现 `forbid bind service`）；
- 恢复 `APP_AUTO_START` / `APP_ASSOC_START` / `GET_USAGE_STATS` 三个 appops 为 allow；
- 恢复电池白名单；
- 确认 `wb_boot_target` / `wb_quiet_mydv` / `wb_exact_resume` / 白名单仍在。

重绑本身会触发一次**伪唤醒**（日志里能看到 5 次纠正），这是正常的，不等于真实待机唤醒测试。

## 5. 完整核查清单

```bash
# 版本 / 哈希
adb shell "dumpsys package com.wb.mydvresume | grep -E 'versionCode|versionName|lastUpdateTime'"
adb shell "sha256sum $(pm path com.wb.mydvresume | sed 's/package://')"

# 服务
adb shell "dumpsys accessibility | grep -oE 'Service\[label=[^,]*|Crashed services:\{[^}]*\}'"
adb shell "pidof com.wb.mydvresume"

# 配置
adb shell "settings get system wb_boot_target"
adb shell "settings get system wb_quiet_mydv"
adb shell "settings get system wb_boot_whitelist"

# 唤醒日志
adb shell "logcat -d -t 20000 -v brief -s MyDvResume:V" | tail -60
python boot_target.py --wake-report
python verify_quiet.py --report
```

v4.0 应看到连续多次 `launched ... (task reuse)`、`legacy fallback=0`、`SecurityException=0`。

v4.1 起还应确认 `WAKE via ... target=` 与**待机前正在用的应用**一致，`launched` 的包名相同；若仍是 `com.github.mytv.dv`，查 `WAKE candidate=... intent=null` 和组件解析是否覆盖该包。

v4.2 起跑 `python verify_autolearn.py --follow`：确认 `versionCode=19`、服务 Bound、`auto-learn scan (bind): 15 user apps`（与 `pm list packages -3` 一致）、`no launchable component / legacy fallback = 0`。装了新应用后应出现 `auto-learn PACKAGE_ADDED: <包名> component=...`；用户做一次真实「暂停 → 待机 → 唤醒」后应出现 `WAKE target from standby record=<新包名>` 与对应的 `launched ... (task reuse)`。

## 6. 真实待机唤醒测试（必须人工）

**不能用 adb 注入电源键**（`input keyevent 26` 会让 5555 掉线且唤不醒）：

1. 在讴歌影视播放页**按暂停**；
2. 用**遥控器**待机；
3. 再用遥控器唤醒；
4. 看是否回到暂停前那个界面并能接着播；
5. 跑 `boot_target.py --wake-report` 看 `standby class=` 与唤醒时序。

## 7. 回退 / 卸载

```bash
python uninstall_resume.py      # 卸载服务
python restore_tcl.py --status  # 查看可还原的电视设置
python restore_tcl.py --this    # 还原本次改动
python restore_tcl.py --all     # 全部还原
```

## 8. 发布后别忘了同步仓库

```bash
cd E:\WorkBuddy\闲聊\TCL
python scripts/sync_and_push.py --message "v4.2.1 auto-learning whitelist"
```

脚本会自动归档新 APK、更新源码/脚本快照、记录版本日志并 push 到 `main`。
