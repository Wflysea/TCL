# 版本演进

所有版本均通过 6553 tcast / `com.tcl.MultiScreenInteraction_TV` 多屏互动推送安装（普通 `adb install` 会被 TCL 签名门拦截）。每次覆盖安装后都要重跑 `finalize_resume.py` 重绑无障碍服务。

版本代号（v3.x / v4.x）是对话里用的名字，`versionCode` / `versionName` 是 APK 清单里的真实值。

| 版本 | versionCode / Name | 时间 | 主要内容 | 结果 |
| --- | --- | --- | --- | --- |
| v1 初始版 | 早期，未归档 | 11-08 | 最小 AccessibilityService，依赖 `onAccessibilityEvent` | 事件根本不派发，唤醒无反应 |
| v2 | 早期 | 11-08 | `SCREEN_ON` / `USER_PRESENT` + 2 秒 `isInteractive()` 轮询 + 服务重绑定三重检测 | 唤醒能拉回应用 |
| v3.0 ~ v3.4 | 早期 | 11-08 ~ 11-13 | 开机自启「C 折中」（UsageStats 事件流 + 本地 `last_app` 兜底、120 秒纠正窗口）；白名单从少量扩到全部自装应用（14 个）；放行 `APP_AUTO_START` / `APP_ASSOC_START`；移除可能撞签名门的 `<queries>` 与 LAUNCHER 声明 | 冷启动可进记忆应用 |
| v3.5 | 9 / 1.8 | 11-13 | 用 `ActivityManager.killBackgroundProcesses` 清掉 myDV 后台音频（此前 `PIP_PAUSE` receiver 不导出、MediaSession 不可控） | 唤醒别的应用不再叠加 myDV 声音 |
| **v3.6** | **10 / 1.9** | 11-13 20:14 | 「精确恢复」：`SCREEN_OFF` 时记录 `last_class`，唤醒时用 `ComponentName(pkg, wakeClass)` + `NEW_TASK\|SINGLE_TOP` 尝试直达原 Activity；加 `isPkgForeground` 跳过重复启动；5 个纠正点 `DELAYS={800,2500,5000,9000,13000}` | 用户实测：**待机前暂停 → 唤醒可以接着播**（后续所有版本的对照基准）。精确恢复本身因 `DetailActivity` 不导出抛 `SecurityException`，catch 后回退 root 启动 |
| v3.7 | 11 / 2.0 | 11-13 20:25 | 维护版：启动前用 `ActivityInfo.exported` 检查，不导出就跳过，不再抛权限异常占纠正窗口 | 推送成功，但去掉了 v3.6 的异常分支 |
| v3.8 | 12 / 2.1 | 11-13 20:32 | 「消除重复启动」：`isPkgForeground` 改为进程级前台探测 + `foregroundTakenOverSince`，首次启动后后续 4 个纠正点全部 `skip repeat launch` | **引入回归**：用户反馈「待机前暂停现在也不行了」。5 次纠正被压成 1 次，TCL 亮屏 2~3 秒后才压桌面，服务那时已不再纠正 |
| v3.9 | 13 / 2.2 | 11-14 18:4x | 改用 launcher 语义 intent（`ACTION_MAIN` + `LEANBACK_LAUNCHER` / `LAUNCHER` + `RESET_TASK_IF_NEEDED`）想把整个任务栈带回前台；放宽跳过条件；恢复多次纠正 | `ActivityNotFoundException`：隐式跨包启动解析不到，自动回退旧的显式组件路径 |
| v3.9.1 | 14 / 2.3 | 11-14 18:44 | 清单加 `QUERY_ALL_PACKAGES`（normal 权限，无 `<queries>` 声明）解决 Android 11 包可见性 | 验证器接受、可见性生效（`component unavailable` → `not exported`），但隐式 launcher intent **仍解析失败**；实测连 `adb shell` 都报 unable to resolve ⇒ TCL 系统级限制 |
| **v3.10** | **15 / 2.4** | 11-14 18:58 | 用户要求「参考 3.6」：从历史记录里提取 v3.6 的 887 行完整源码原样覆盖，清单也回退（移除 `QUERY_ALL_PACKAGES`），只改注释与日志标记 | 逻辑 100% 复原、5 次纠正节奏恢复，**但实测仍落在首页** ⇒ 证明问题不在服务代码改动，而在「同一份代码遇到不同的待机页面状态」 |
| **v4.0** | **16 / 3.0** | 11-14 19:38 | **找到真因并修复**：显式组件 + `ACTION_MAIN` + `CATEGORY_LAUNCHER` + `NEW_TASK\|RESET_TASK_IF_NEEDED\|NO_ANIMATION`（**去掉 `SINGLE_TOP`**），把整个任务栈原样带回前台而不新建首页；删除每次必抛异常的精确恢复分支；恢复 5 次纠正并取消 v3.8 的跳过判断；新增 legacy fallback | 重绑实测 10 次 `task reuse`、`fallback=0`、`SecurityException=0`；`mCurrentFocus` 保持在 `DetailActivity`，栈 = Home → History → Detail，**无多余首页**；**11-14 20:09 用户真实遥控器「暂停 → 待机 → 唤醒」实测通过 ✅**（见下节） |
| **v4.1** | **17 / 3.1** | 11-15 19:22 | 修复「唤醒拉错应用」：静态组件表补 `rocks.aston.hongguotv/.MainActivity`；`resolveWakeTarget()` 优先采用 SCREEN_OFF 持久化的待机包名（带 7 天新鲜度校验）；`resolveBootIntent()` 增加从 UsageEvents / 待机记录取真实 Activity 类的通用兜底 | 重绑实测两段唤醒共 **10 次 `launched rocks.aston.hongguotv`**、`mydv_launched=0`、`legacy fallback=0`；目标与待机前一致，设备哈希与本地一致 `bf40c492…1c5` |
| **v4.2** | **18 / 3.2** | 11-15 20:08 | **自动学习白名单（中间构建）**：清单加 `QUERY_ALL_PACKAGES`；绑定时全量扫描自装应用、`PACKAGE_ADDED/REPLACED/REMOVED` 增量学习并缓存 launcher 组件；`isAllowed()` = 静态白名单 ∪ 运行时自装集合；`resolveBootIntent()` 改为六级组件解析。**v4.0 任务栈复用启动逻辑零改动** | 首次扫描 29 个包、缓存 16 个组件；重绑实测 11 次 `launched rocks.aston.hongguotv (task reuse)`、`myDV=0`、无 fallback；随后发现 29 个含系统更新包，需收紧 |
| **v4.2.1** | **19 / 3.3** | 11-15 20:12 | 收紧自动学习集合到 `pm list packages -3` 语义（`FLAG_SYSTEM == 0`），不再把 ~13 个 `FLAG_UPDATED_SYSTEM_APP` 系统更新包当作自装应用，避免误拉系统界面；新增只读核查脚本 `verify_autolearn.py` | 设备实测 `userApps=15` 与 `pm -3`（16 个含服务自身、15 个可学习）一致；唤醒回到 `com.cctv.yangshipin.app.androidq` 的 `DetailActivity`，8 次 task reuse、`myDV=0`、无 fallback；设备内 `base.apk` 哈希与本地一致 `4a50c6b6…3ee` |

---

## v4.0 的根因（最重要的一条）

「有声音、没画面」说明播放器还在后台正常播，**只是界面被新压上来的首页盖住了**，不是播放页被销毁。

- 讴歌影视 `HomeActivity` 是 `singleTop`，栈顶却是 `DetailActivity`（暂停后停在详情页）。
- v3.6 / v3.10 用 `HomeActivity + SINGLE_TOP` 启动，`SINGLE_TOP` 不命中，Android 就**新建一个首页压上去**。A/B 实证：任务栈从 3 个变 4 个。
- v4.0 用显式组件 + `RESET_TASK_IF_NEEDED`（去掉 `SINGLE_TOP`），实测在桌面已在前台时返回 `its current task has been brought to the front`，**栈顶仍是原页面、一个 Activity 都没新建**。
- 显式组件绕开 TCL 的隐式解析限制；`RESET_TASK_IF_NEEDED` 提供 launcher 语义。这正是 v3.6 缺「不新建首页」、v3.9 缺「显式组件」的合集。

已实证排除的替代方案：全局返回键被首页吞掉；`DetailActivity` 连 `adb shell` (uid 2000) 都报 `not exported`；`LEANBACK_LAUNCHER` 与标准 `LAUNCHER` 的隐式 `am start` 都无法解析；应用有 3 个 exported receiver 但未用于本方案。详见 [docs/troubleshooting.md](docs/troubleshooting.md)。

## v4.0 真机实测记录（最终确认）

**2026-11-14 20:09，用户用真实遥控器完成「播放页按暂停 → 待机 → 唤醒」，成功回到暂停前界面并接着播放。** 之前所有版本缺的都是这一步——我不能用 `input keyevent 26` 代替，会让 5555 掉线且唤不醒。

设备只读取证（v4.0 / `versionCode 16` / `3.0`，进程 31266 存活，小 T 助手 + myDV Resume 两个无障碍服务 Bound）：

- 服务日志出现两次真实 `SCREEN_OFF`，每次都记录 `standby class=...DetailActivity`（`com.cctv.yangshipin.app.androidq`）；
- 唤醒后 `WAKE foreground event gave com.cctv.yangshipin.app.androidq`、`WAKE class from standby record: ...DetailActivity`；
- 各纠正点连续多次 `launched ... (task reuse) top=...DetailActivity`，**没有** `legacy fallback`、**没有** `SecurityException`；
- `quiet myDV background audio` 在每次唤醒时照常执行（没有叠加 myDV 声音）；
- 当前 `mCurrentFocus = ...DetailActivity`；任务栈 = `HomeActivity → SearchActivity → FastSearchActivity → DetailActivity`（4 个），**没有多压一个新首页** —— 这正是 v3.6 / v3.10 会出问题的地方。

结论：显式组件 + `RESET_TASK_IF_NEEDED` + 去掉 `SINGLE_TOP` 的方案在真实待机唤醒场景成立；5 次纠正、静音、白名单、冷启动逻辑保持原样。**项目功能闭环。**

## v4.1 的根因：唤醒打开错的应用

**症状**：2026-11-15 18:51 真实待机唤醒后，服务连续 5 次把 `com.github.mytv.dv`（myDV 默认目标）拉到前台，而待机前、以及用户随后切回的都是红果TV `rocks.aston.hongguotv`。日志里 `WAKE class from standby record` / `top=` 明明写着 `rocks.aston.hongguotv.MainActivity`，`WAKE candidate` 却拿不到可启动的 intent。

**根因**：`wb_boot_whitelist` 有 14 个自装应用，但 `KNOWN_COMPONENTS` 静态组件表只映射了 13 个 —— **恰好缺红果TV**（它是后来加进白名单的）。Android 11 的包可见性限制使 `getLaunchIntentForPackage()` / `getLeanbackLaunchIntentForPackage()` 对别的包返回 null，`resolveBootIntent("rocks.aston.hongguotv")` 因此返回 null；`resolveWakeTarget()` 的 `probe != null` 判定失败，就静默回退到 `TARGET`（myDV）。开机冷启动走的是同一张表，所以同样会出错。

**修复**（三点，均为增量、不影响 v4.0 的任务栈复用）：

1. `KNOWN_COMPONENTS` 补 `{"rocks.aston.hongguotv", "rocks.aston.hongguotv/.MainActivity"}`（用 `cmd package resolve-activity` 实测确认）。
2. `resolveWakeTarget()` 优先读 `SCREEN_OFF` 时持久化的 `last_class_pkg`，新增 `last_class_at` 时间戳与 7 天新鲜度校验；这样不再依赖只有 24 小时窗口、且会被唤醒后 HOME / 任务管理器事件污染的 UsageEvents，超长待机也不会选错。
3. `resolveBootIntent()` 增加通用兜底：静态表未命中时，从 UsageEvents 最近一次前台事件或 SCREEN_OFF 记录取真实 Activity 类，构造显式 `ComponentName`。以后新装应用加入白名单也不会再回退 myDV。

**验证**：覆盖安装并重绑后，日志 `WAKE via rebind seq=1 target=rocks.aston.hongguotv`、`WAKE candidate=... intent=ComponentInfo{rocks.aston.hongguotv/rocks.aston.hongguotv.MainActivity}`；两段唤醒共 10 次 `launched rocks.aston.hongguotv (task reuse)`，`launched com.github.mytv.dv=0`；`mCurrentFocus` 保持在红果TV，栈里没有多压首页。首次重绑时 `fresh=false` 属预期（旧版本没有写时间戳），走了 `recentWhitelistedApp()` 兜底并正确解析；用户下一次真实待机后即会命中 `WAKE target from standby record=` 分支。

## v4.2：自动学习白名单（装新应用不再需要电脑）

**问题**：v4.1 的 `wb_boot_whitelist` 是 `boot_target.py --all-apps` 生成的一次性静态快照，`KNOWN_COMPONENTS` 也是手工维护的静态表。电视以后每装一个新应用，都得连电脑重跑脚本、甚至改源码补组件映射，否则唤醒会回退到 myDV。用户选择「B 自动学习版」。

**做法**（`ResumeService.java`）：

1. **看得见**：清单加 `android.permission.QUERY_ALL_PACKAGES`。这是普通安装时权限，v3.9.1 已实证 TCL 验证器接受；**不写 `<queries>`、不声明任何 LAUNCHER/HOME**，签名门不受影响。Android 11 包可见性由此打开，`getInstalledPackages()` / `getLaunchIntentForPackage()` 对别的包才有结果。
2. **学得到**：`onServiceConnected()` 全量扫描一次 `pm -3` 语义的自装应用；动态注册 `PACKAGE_ADDED / PACKAGE_REPLACED / PACKAGE_REMOVED` 接收器做增量学习（动态注册不受 Android 8+ 隐式广播限制）；`SCREEN_OFF` 再扫一次作为兜底。结果存进 `dynamicAllow` 集合，并把每个包解析出的 launcher 组件以 `cmp.<pkg>` 缓存进 SharedPreferences，重启后仍在。
3. **判得准**：`isAllowed()` = 静态 `wb_boot_whitelist` ∪ 动态自装集合；`lastAllowedForeground()` / `recordStandbyClass()` / `recentWhitelistedApp()` 全部改用它，所以新装应用会自动进入「待机前记录 → 唤醒目标」链路。桌面、安装器、系统 UI、服务自身由 `SKIP_PKGS` 硬排除。
4. **拉得起**：`resolveBootIntent()` 改成六级解析 —— ① `getLeanbackLaunchIntentForPackage()` ② `getLaunchIntentForPackage()` ③ 限定包名的显式 `MAIN+LAUNCHER` 查询 ④ 静态组件表 ⑤ 缓存的已学组件 ⑥ `exported` 的 MAIN Activity / UsageEvents 观察类。**只取 `ComponentName`**。

**关键约束**：`launch()` 的 v4.0 写法（显式组件 + `ACTION_MAIN` + `CATEGORY_LAUNCHER` + `NEW_TASK|RESET_TASK_IF_NEEDED|NO_ANIMATION`、**无 `SINGLE_TOP`**）、5 个纠正点、`quietMyDv()`、冷启动逻辑**一行未改**。自动学习只替换「组件从哪来」，不碰已实测通过的任务栈复用。

**v4.2.1 收紧**：v4.2 初版把 `FLAG_UPDATED_SYSTEM_APP`（TCL 预装应用被 OTA 更新的那些）也算成自装应用，扫描到 29 个而不是 15 个；它们带 exported MAIN Activity，理论上可能被选成唤醒目标并拉起系统界面。改为严格 `FLAG_SYSTEM == 0`，与 `pm list packages -3` 对齐。静态白名单仍可显式覆盖任何这类应用。

**配置**（`settings put system ...`，无需重绑）：

| 键 | 含义 |
| --- | --- |
| `wb_auto_learn` | 默认开；`0` / `off` 退回 v4.1 的静态白名单行为 |
| `wb_learn_exclude` | 永不恢复的包名，逗号分隔（即使它是自装应用） |

**核查**：`python verify_autolearn.py --follow`（只读）会打印版本、无障碍绑定、两个开关、设备自装应用数、服务扫描结果、学到的新包、最近的唤醒决策与 `launched` 记录，并检查有无 `no launchable component` / `legacy fallback`。另可用 `--auto-learn-on/off`、`--exclude`、`--clear-log`。

**实测**（2026-11-15，v4.2.1 / 19 / 3.3）：

```
auto-learn scan (bind): 15 user apps, 0 new components
service connected v4.2.1 (auto-learn), userApps=15
WAKE candidate=com.cctv.yangshipin.app.androidq intent=ComponentInfo{.../HomeActivity}
WAKE class from usage events: com.github.tvbox.osc.ui.activity.DetailActivity
launched com.cctv.yangshipin.app.androidq (task reuse) top=...DetailActivity  (x8)
```

`myDV=0`、`legacy fallback=0`、`no launchable component=0`；设备内 `base.apk` 与本地 APK 的 sha256 一致。首次重绑 `fresh=false` 属预期（旧的待机记录没有时间戳或已过期），**用户下一次真实「暂停 → 待机 → 唤醒」** 即会命中 `WAKE target from standby record=`。

**边界**：`APP_AUTO_START` / `APP_ASSOC_START` 是 TCL 定制 appops，`cmd appops set` 需要 shell 权限，普通第三方应用无法给别的应用授权。所以「待机 → 唤醒」这条主路径已完全脱离电脑；但**断电冷开机**想自动进某个新装应用时，TCL 仍可能拦关联启动，可选跑一次 `python verify_autolearn.py --allow-autostart`（一次性、非必需）。

## APK 指纹

| 版本 | sha256（前 8 位） | 大小 |
| --- | --- | --- |
| v3.7 | `de3319ee…9ffe` | 20946 B |
| v3.8 | `b9496034…07cc` | 20946 B |
| v3.9 | `d63d67cf…3702` | 20946 B |
| v3.9.1 | `b2c0beb3…aa83` | 20946 B |
| v3.10 | `548ce646…1960` | 20946 B |
| v4.0 | `bdc3c83c…85d3` | 20946 B |
| **v4.1** | **`bf40c492…1c5`** | **20946 B** |
| v4.2（中间构建，成品未归档） | `79cbd45c…e63` | 25042 B |
| **v4.2.1** | **`4a50c6b6…3ee`** | **25042 B** |

所有版本 V1/V2/V3 签名通过，清单均不含 HOME / LAUNCHER / `<queries>` 声明（否则会触发 TCL 签名门）。v4.2 起新增的 `QUERY_ALL_PACKAGES` 是普通 `<uses-permission>`，v3.9.1 已验证验证器接受。v4.2 之后 APK 变大是因为新增自动学习代码使 `classes.dex` 从 ~24 KB 增至 29840 B。


## 工具侧修复（不改 APK 版本）

| 日期 | 文件 | 内容 |
| --- | --- | --- |
| 2026-11-15 | `scripts/push_apk.py` | 安装成功后不再立即关闭 tcast socket 与 APK HTTP server：新增 `finish()` 优雅收尾（`GRACE_SECONDS = 10`，保持 `150>>` 心跳、记录 `late TV state`），修复「安装完成瞬间闪出下载失败」的假提示；并修正 `stage=2` 未真正切换到下一个 URL 的逻辑。v4.2 / v4.2.1 两次推送均实测 `stage=5 / installed` 且无假提示。根因与日志证据见 [docs/troubleshooting.md](docs/troubleshooting.md)。 |
| 2026-11-15 | `scripts/build_apk.py` | 构建日志脱敏：`run()` 现在把命令行里的 `--ks-pass pass:xxx` / `--key-pass pass:xxx` 打印成 `pass:<REDACTED>`，子进程输出同样过滤。原实现会把签名口令原样打到 stdout/CI 日志里，是一个真实的凭据泄漏点（本次构建因此触发内容安全拦截）。 |
| 2026-11-15 | `scripts/verify_autolearn.py`（新增）、`scripts/push_apk.py` | 新增只读核查脚本：版本 / 无障碍绑定 / 自动学习开关 / 设备自装应用数 / 扫描与学习日志 / 唤醒目标 / fallback 计数；支持 `--auto-learn-on/off`、`--exclude`、`--allow-autostart`（可选冷启动 appops）、`--clear-log`、`--follow`。`push_apk.py` 的 `VERSION` 随 versionCode 同步到 `19`。 |
| 2026-11-15 | `scripts/push_apk.py` | 修复「推送时看不到版本号」。根因：tcast `INSTALL` 帧的 `versionCode` 字段 TCL 弹窗不渲染，且脚本 `VERSION` 是硬编码、控制台也不打印。现改为从签名 APK 自动读取版本（aapt2 badging → 清单兜底），删除硬编码常量；推送前打印含 `versionCode` / `versionName` / sha256 / 设备已装版本的横幅，成功后打印 `VERSION CHECK` before → after；弹窗 label 拼成 `myDV Resume 3.3 / vc19 (v4.2.1)`，下载文件名带 `v3.3-vc19`（字节副本，退出自动删除）。新增 `--info-only`、`--plain-label`。**APK 无改动，设备仍是 v4.2.1（19 / 3.3）**。 |
