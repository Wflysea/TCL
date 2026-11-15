# ADB 命令速查

设备 `192.168.1.26:5555`（TCL 75V8L-C3，Android 11）。ADB 在
`E:\WorkBuddy\闲聊\_tmp\platform-tools\adb.exe`，下文简写 `adb`。

> 每次终端调用之间 adb daemon 会重启，把 `adb connect` 与后续检查放**同一条命令**里：
> `adb connect 192.168.1.26:5555 >/dev/null && adb -s 192.168.1.26:5555 shell "..."`

## 连接与基本信息

```bash
adb connect 192.168.1.26:5555
adb -s 192.168.1.26:5555 get-state
adb shell "getprop ro.product.model; getprop ro.build.version.sdk"
adb shell "cat /proc/sys/kernel/random/boot_id; cat /proc/uptime"
```

## 前台 / 任务栈（排障最常用）

```bash
adb shell "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'"
adb shell "dumpsys activity activities | grep -E 'mResumedActivity|topResumedActivity'"
adb shell "dumpsys activity activities | grep 'Activities=\['"      # 任务栈从底到顶
adb shell "dumpsys usagestats | grep -E 'ACTIVITY_RESUMED|ACTIVITY_PAUSED'"
adb shell "logcat -d -b events -t 40000 -v threadtime" | grep -E "am_resume_activity|wm_task_to_front|screen_toggled"
```

## 声音 / 媒体

```bash
adb shell "dumpsys audio | grep -Ei 'player|piid|state:started'"
adb shell "dumpsys media_session | grep -Ei 'package|state=PlaybackState|active'"
```

## 包与精简（可逆）

```bash
adb shell "pm list packages -3"                     # 第三方应用
adb shell "pm disable-user com.tcl.guard"           # 禁用电视卫士
adb shell "pm disable-user com.tcl.appmarket2"      # 禁用应用商店
adb shell "pm enable <包名>"                        # 单个恢复
adb shell "pm list packages -d"                     # 已禁用列表
python restore_tcl.py --status / --this / --all     # 批量还原（推荐）
```

## 服务状态 / 无障碍绑定

```bash
adb shell "dumpsys package com.wb.mydvresume | grep -E 'versionCode|versionName|lastUpdateTime'"
adb shell "sha256sum $(pm path com.wb.mydvresume | sed 's/package://')"
adb shell "pidof com.wb.mydvresume"
adb shell "dumpsys accessibility | grep -oE 'Service\[label=[^,]*|Crashed services:\{[^}]*\}'"
adb shell "settings get secure enabled_accessibility_services"
adb shell "settings put secure accessibility_enabled 1"
adb shell "logcat -d -t 20000 -v brief -s MyDvResume:V" | tail -80
```

## 后台策略（覆盖安装后会被重置）

```bash
adb shell "cmd appops set com.wb.mydvresume APP_AUTO_START allow"
adb shell "cmd appops set com.wb.mydvresume APP_ASSOC_START allow"
adb shell "cmd appops set com.wb.mydvresume GET_USAGE_STATS allow"
adb shell "cmd deviceidle whitelist +com.wb.mydvresume"
adb shell "cmd appops get com.wb.mydvresume"
adb shell "cmd deviceidle whitelist | grep mydvresume"
```

给目标播放器的额外保护（可撤销）：

```bash
adb shell "cmd deviceidle whitelist +com.cctv.yangshipin.app.androidq"
adb shell "cmd deviceidle whitelist -com.cctv.yangshipin.app.androidq"   # 撤销
```

## 项目配置开关

```bash
adb shell "settings get system wb_boot_target"
adb shell "settings get system wb_boot_whitelist"
adb shell "settings get system wb_quiet_mydv"
adb shell "settings get system wb_exact_resume"
```

一键脚本：`python boot_target.py --status / --list-apps / --all-apps / --allow-autostart / --quiet-on / --quiet-off / --exact-on / --exact-off / --wake-report / --boot-report`。

v4.2 自动学习：`python verify_autolearn.py --follow`（只读核查）/`--auto-learn-on` / `--auto-learn-off` / `--exclude "包1,包2"` / `--clear-log` / `--allow-autostart`（可选冷启动授权）。装新应用后**不需要**再跑 `--all-apps`。

## 启动应用（诊断用，注意权限边界）

```bash
# 成功：v4.0 的任务栈复用写法（显式组件 + launcher 语义）
adb shell "am start -n com.cctv.yangshipin.app.androidq/com.github.tvbox.osc.ui.activity.HomeActivity -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -f 0x10210000"

# 会失败（实测）：
#   隐式 MAIN+LAUNCHER        -> ActivityNotFoundException / unable to resolve
#   DetailActivity / PlayActivity -> not exported from uid 10068
```

## 禁止 / 注意

```bash
# 禁止：会让 5555 掉线且唤不醒，真实待机只能用遥控器
# adb shell "input keyevent 26"

# 诊断时可安全注入（非电源键，无残留设置）
adb shell "input keyevent 3"      # HOME
adb shell "input keyevent 4"      # BACK
```

## 控件树导出

```bash
adb shell "uiautomator dump --compressed /sdcard/wb_ui.xml"
adb shell "cat /sdcard/wb_ui.xml" > wb_ui.xml     # adb pull 常因权限 600 失败，用 cat
```
