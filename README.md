# TCL 75V8L-C3 · myDV Resume

围绕一台 TCL 电视做的完整工程记录：一个**纯电视端、脱离电脑**运行的无障碍服务（待机唤醒后回到原播放界面），以及精简、备份、还原、厂家远控审计、后台加固、诊断与推送的全部脚本。

- 仓库：<https://github.com/Wflysea/TCL>
- 当前版本：**v4.4** / `versionCode 21` / `versionName 3.5`
- **状态：✅ 2026-11-14 用户用真实遥控器完成「暂停 → 待机 → 唤醒」测试，成功回到暂停前界面并接着播放**（[实测记录](CHANGELOG.md)）
- **v4.4（2026-11-20）两项调整**：① **唤醒严格只启动一次**——单次 `startActivity` 安排在唤醒后 4000ms（避开 TCL 在 2～3 秒时推 HOME），并用 `wakeLaunchOnce` 硬 gate 保证重复事件不再启动；v4.0 的 task-reuse 启动方式一行未改。② **彻底移除推送横幅**——v4.3 的 `TYPE_ACCESSIBILITY_OVERLAY` 版本横幅与其 `PUSH_BANNER` 接收器从服务和脚本中全部删除；版本号只在 PC 控制台显示，电视端不再画横幅。冷开机（开机自启）逻辑不受影响。
- **v4.3（2026-11-15）推送横幅（已被 v4.4 移除）**：曾在左下角画版本横幅；因该弹窗文案写死在系统资源、协议字段不渲染，且用户不再需要，v4.4 已彻底删除。
- **v4.2 / v4.2.1（2026-11-15）自动学习版**：以后电视**新装应用不用连电脑、不用改白名单**——服务自己扫描自装应用、监听 `PACKAGE_ADDED`、缓存启动组件；待机唤醒自动回到新应用原来的界面。v4.1 的「待机记录优先选目标」继续保留。
- **v4.1（2026-11-15）**：修复「唤醒拉错应用」——待机前在红果TV，唤醒却固定拉 myDV。根因是静态组件表缺少 `rocks.aston.hongguotv` 的映射；已补齐并改为按 SCREEN_OFF 待机记录选目标。
- 版本演进见 [CHANGELOG.md](CHANGELOG.md)

---

## 1. 设备与环境

| 项 | 值 |
| --- | --- |
| 电视 | TCL 75V8L-C3，Android 11 (SDK 30)，armeabi-v7a |
| 设备代号 | `tc8000_ay30a2` |
| ADB | 网络调试 `192.168.1.26:5555` |
| 目标应用 | myDV `com.github.mytv.dv`（官方 2.3.44）、讴歌影视 `com.cctv.yangshipin.app.androidq`、红果TV `rocks.aston.hongguotv` |
| 服务包名 | `com.wb.mydvresume` |
| 构建环境 | 本机 `C:\Temp\wbapk`，纯 aapt2 + javac + dx + apksigner，无 Gradle/Android Studio |

**三条硬约束**（踩过坑，务必遵守）：

1. `adb install` 会被 TCL 签名门拦截（`INSTALL_FAILED_VERIFICATION_FAILURE`），必须走 **6553 tcast / 多屏互动**推送，且在电视端按「右 → 同意」确认。
2. **不要用 `input keyevent 26` 注入电源键**：会让 5555 掉线且唤不醒。真实待机/唤醒只能用遥控器。
3. 每次覆盖安装后，无障碍绑定与后台策略会被系统重置，**必须重跑** `finalize_resume.py`。

---

## 2. 这个服务做什么

`ResumeService` 是一个 AccessibilityService，不声明 HOME / LAUNCHER / LEANBACK_LAUNCHER，靠系统重绑定常驻：

- **唤醒恢复**：监听 `SCREEN_ON` / `USER_PRESENT`，加 2 秒轮询 `isInteractive()` 和长间隔 `elapsedRealtime`、服务重绑定三重检测；唤醒后在 `0.8 / 2.5 / 5 / 9 / 13 秒` 共 5 个纠正点，把待机前的应用**整个任务栈**原样带回前台（对抗 TCL 亮屏后 2~3 秒才把桌面抢到前台的行为）。
- **冷启动进记忆应用**（C 折中）：靠 `boot_id` / `elapsedRealtime` 负间隔判冷启动，`UsageStatsManager` 事件流 + 本地 `last_app` 兜底；默认 myDV，白名单内记忆上次应用，否则回退；120 秒纠正窗口，用户按键或主动开别的应用即取消劫持。
- **myDV 后台音频静音**：目标不是 myDV 时用 `killBackgroundProcesses` 清掉 myDV 后台音频，避免唤醒别的应用时叠一层声音。
- **自动学习白名单**（v4.2）：服务绑定时全量扫描 `pm list packages -3` 意义下的自装应用，`PACKAGE_ADDED / REPLACED / REMOVED` 增量学习，并把每个应用的 launcher 组件缓存进 SharedPreferences；`isAllowed()` = 静态 `wb_boot_whitelist` ∪ 运行时自装集合。**装完新应用直接待机唤醒即可，不必再跑 `boot_target.py --all-apps`**。系统应用、桌面、安装器、服务自身永不入集；`wb_auto_learn=0` 可退回静态白名单，`wb_learn_exclude` 可排除指定包。
- **精确恢复**：v4.0 已移除该分支（播放页不导出，第三方无法启动；改由任务栈复用解决）。

关键配置（`settings put system ...`）：

| 键 | 含义 |
| --- | --- |
| `wb_boot_target` | 冷启动默认目标包 |
| `wb_boot_whitelist` | 允许记忆的自装应用白名单（逗号分隔） |
| `wb_quiet_mydv` | 非 myDV 目标时静音 myDV 后台音频（1=开） |
| `wb_exact_resume` | 精确恢复开关（v4.0 起不再使用该分支，保留兼容） |
| `wb_auto_learn` | 自动学习开关（默认开；`0` / `off` 退回静态白名单） |
| `wb_learn_exclude` | 永不恢复的包名，逗号分隔（即使它是自装应用） |

更细的原理见 [docs/architecture.md](docs/architecture.md)。

---

## 3. 目录结构

```
TCL/
├── README.md                  本文件
├── CHANGELOG.md               v1 → v4.4 完整版本演进
├── .gitignore                 排除私钥 / 令牌 / 大二进制
├── apk/                       当前版本完整源码
│   ├── AndroidManifest.xml
│   ├── src/com/wb/mydvresume/ResumeService.java
│   ├── res/                   strings.xml / resume_config.xml
│   ├── build_apk.py           构建 + 签名脚本（口令已脱敏）
│   └── README.md              构建说明与密钥说明
├── releases/                  每个 versionCode 一份已签名 APK
├── history/                   各版本源码快照（v1 / v3.6 / v3.9.1 / v3.10 / v4.0 / v4.1）
├── scripts/                   全部运维与诊断脚本
│   └── sync_and_push.py       ★ 改完即同步 + commit + push
├── device-backup/             精简前的设备状态快照（已脱敏）
└── docs/
    ├── architecture.md        服务原理、唤醒机制、配置开关
    ├── build-and-push.md      构建 / 推送 / 重绑 / 验证全流程
    ├── troubleshooting.md     根因实证与已知边界
    ├── adb-cheatsheet.md      常用命令与撤销方法
    └── device-setup.md        cleanyourtv 精简、OTA、禁用清单与还原
```

---

## 4. 快速开始

```bash
# 1) 构建并签名（需要本地工具链，见 docs/build-and-push.md）
cd C:\Temp\wbapk && python build_apk.py

# 2) 推送到电视（电视端按「右 → 同意」）
#    版本号只在 PC 控制台显示；v4.4 起电视端不再有横幅
cd E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup && python push_apk.py
python push_apk.py --info-only     # 只查本地 APK 与电视已装版本，不推送

# 3) 覆盖安装后重绑无障碍服务 + 恢复后台策略（必做）
python finalize_resume.py

# 4) 核查
python boot_target.py --status
python boot_target.py --wake-report
python verify_quiet.py --report
python verify_autolearn.py --follow    # v4.2：自动学习集合 / 唤醒目标核查
```

---

## 5. 每次更改都推送到本仓库

**这是本仓库的固定工作流**：任何改动（源码、脚本、文档、设备快照）完成后立即执行

```bash
cd E:\WorkBuddy\闲聊\TCL
python scripts/sync_and_push.py
```

脚本会：

1. 从本地工作副本 `C:\Temp\wbapk` 与 `_tmp\tcl75v8l_backup` 同步全部白名单文件到仓库对应目录；
2. 把当前签名 APK 归档为 `releases/MyDvResume-vc<versionCode>.apk`（不覆盖旧版本，自动形成版本历史）；
3. 对 `getprop.txt` 等设备快照脱敏（序列号、密码类字段、GitHub 令牌）；
4. `git add -A` → 有变更才 commit（自动带时间戳与 versionCode）→ `git push -u origin main`。

常用参数：`--message "说明"` 自定义提交信息、`--no-push` 只提交不推送、`--dry-run` 只预览变更。推送走 SSH（`git@github.com:Wflysea/TCL.git`），不需要任何令牌。

**端到端验证**（2026-11-14）：首次导入 66 个文件（约 444 KB）后，又用本脚本跑了一次「改文档 → 自动 commit → push」实测，本地 `main` 与远端一致。此后每次改动都由它收口，不需要手动敲 git 命令。

---

## 6. 安全说明

这是**公开仓库**，以下内容按设计**不入库**（`.gitignore` + 同步白名单双重保证）：

- `mydvresume.jks` 签名私钥、`C:\Temp\wbapk\.keystore_pass` 口令文件；
- 任何 GitHub PAT / API 凭据；
- 从电视拉取的第三方 APK（`ougo_check.apk` 42 MB、`mydv_installed_2.3.44.apk` 13 MB）、`recv_dis.txt` 327 MB 反编译文本、`dump_classes*.bin` 等中间产物；
- 构建工具链二进制（`tools/`，约 85 MB）、`classes/` / `dexout/` 编译产物。

`device-backup/` 里的系统 dump 已把设备序列号等标识替换为 `<REDACTED>`。设备状态类文件只含包名、设置项与系统属性，可安全公开。

**重新构建时的密钥**：仓库不含私钥，直接用仓库里的源码签名会得到不同签名，无法覆盖安装现有服务。原私钥仅保存在本机 `C:\Temp\wbapk\mydvresume.jks`（口令在同目录 `.keystore_pass`）。迁移到新机器时请自行用 `keytool` 生成新证书，并卸载旧服务后重装。详见 [apk/README.md](apk/README.md)。

---

## 7. 已知边界

- 讴歌影视 `DetailActivity` / `PlayActivity` 均 `exported=false`，第三方服务**无法直接启动**；v4.0 的做法是把整个任务栈原样带回，让待机前那个界面（详情页，带「继续播放」）重新成为栈顶。
- TCL 对第三方服务的**隐式** `MAIN/LAUNCHER` intent 拒绝解析（连 `adb shell` 都报 unable to resolve），所以必须用**显式组件**。
- 回桌面后 TCL 会杀第三方播放器并清任务栈；一旦栈被清掉，任何启动都只能进首页。
- 电脑侧守护进程与计划任务**保持停用**，全部逻辑都在电视端。
- **自动学习的边界**：服务能自动识别并恢复新装应用的「待机 → 唤醒」路径；但 TCL 的 `APP_AUTO_START` / `APP_ASSOC_START` appops 只能由 adb 设置，普通第三方应用无法给别的应用授权。所以**断电冷开机**后想自动进某个新装应用，可选跑一次 `python verify_autolearn.py --allow-autostart`（一次性、非必需）。
- 精确恢复、launcher 隐式 intent、全局返回键弹栈、广播拉起等替代方案的实测结论见 [docs/troubleshooting.md](docs/troubleshooting.md)。
