# 排障与根因实证

按症状组织，每条都标了当时拿到的设备证据。改代码前先对照这里，很多坑已经踩过并排除了。

## A. 唤醒后「进应用了、在首页、有声音没画面」

**结论（v4.0 真因）**：播放器还在后台正常播，只是界面被**服务自己新建的首页**盖住了。

- `dumpsys audio` 里 `uid=10068 piid:7615 state:started`（讴歌影视自己的播放器），myDV 已被 `quietMyDv` 杀掉（`WIN DEATH ...com.github.mytv.dv/.MainActivity`）⇒ 声音来自目标应用，不是 myDV。
- `dumpsys activity activities` 实证：待机前那个 `DetailActivity` **一直没被销毁**，只是被新压上来的 `HomeActivity` 盖住。
- 应用清单：`HomeActivity launchMode=0x1 (singleTop)` 且 `MAIN/LAUNCHER/LEANBACK_LAUNCHER` exported=true；`LivePlayActivity / DetailActivity / PlayActivity launchMode=0x2 (singleTask)` 且无 intent-filter ⇒ `exported=false`。
- A/B 实证：模拟 v3.6 的 `am start -n <HomeActivity> --activity-single-top`，栈从 3 个变 **4 个**（多出一个新首页）。`SINGLE_TOP` 在栈顶是详情页时不命中，Android 就新建一个首页压上去。
- **解法**：显式组件 + `ACTION_MAIN` + `CATEGORY_LAUNCHER` + `NEW_TASK|RESET_TASK_IF_NEEDED|NO_ANIMATION`（去掉 `SINGLE_TOP`）。桌面在前台时实测返回 `its current task has been brought to the front`，栈一个都没变、栈顶仍是原页面。

> 这也解释了「把 v3.6 代码 100% 恢复仍不行」：同样代码，待机时停在的页面状态不同，结果就不同。

**最终验证（2026-11-14 20:09）**：用户用真实遥控器完成「暂停 → 待机 → 唤醒」并确认成功。设备日志显示两次真实 `SCREEN_OFF` 都记录 `standby class=...DetailActivity`，唤醒后连续多次 `launched ... (task reuse) top=...DetailActivity`，无 `legacy fallback` / `SecurityException`，`mCurrentFocus` 保持在 `DetailActivity`，任务栈没有多压首页。完整证据见 [CHANGELOG.md 的真机实测记录](../CHANGELOG.md#v40-真机实测记录最终确认)。**本症状在 v4.0 已解决，不要再往「播放页不导出」方向排查。**

## B. 「待机前暂停突然也不行了」（v3.8 回归）

- v3.8 把「消除重复启动」当优化：`isPkgForeground` 改成进程级 `RunningAppProcessInfo` 探测，首次启动即判为「已在前台」，5 个纠正点里后续 4 个全部 `skip repeat launch … starts=1`。
- 服务日志实证：`SCREEN_OFF` 记 `DetailActivity` → 唤醒 `WAKE via poll` → `HOME after wake since=568ms / 746ms`，即 TCL **亮屏不到 1 秒就把桌面抢到前台**；服务那时已经不再纠正。
- 系统 events：`wm_task_to_front [0,2]`（桌面）、`TclActivityTaskManagerService: setBootSource cmpName:com.tcl.cyberui/.MainActivity`、`SourceManager: setBootSourceForApp set E_BOOT_INPUT_STORAGE` ⇒ TCL 唤醒时主动切回桌面/启动源。
- **结论：那几次「重复启动」不是日志噪音，正是对抗 TCL 延迟压桌面的机制。** v4.0 已恢复 5 次纠正并取消跳过判断（新启动方式幂等，重复不会叠页面）。

## C. 「直接回到播放页」为什么做不到

- `SCREEN_OFF` 时服务记录的 `standby class=...DetailActivity`，**播放页本来就已不在栈顶**（暂停后退回详情页，或 TCL 待机关掉 PlayActivity）。
- `PlayActivity` / `DetailActivity` 都 `exported=false`：v3.6 精确恢复实测 `java.lang.SecurityException: Permission Denial ... not exported from uid 10068`；连 `adb shell`（uid 2000）执行 `am start -n ...DetailActivity` 也被拒。
- 所以第三方服务**永远无法直接启动播放页**。v4.0 改为把整个任务栈原样带回，让待机前那个界面（详情页，带「继续播放」）重新成为栈顶。

## D. 已实证排除的替代方案

| 方案 | 实测结果 |
| --- | --- |
| 隐式 `MAIN + LEANBACK_LAUNCHER` 启动（v3.9） | `ActivityNotFoundException`；连 `adb shell am start -a MAIN -c LEANBACK_LAUNCHER -p <pkg>` 都报 unable to resolve |
| 标准 `MAIN + LAUNCHER` 隐式启动 | `cmd package resolve-activity --brief` **能**解析到 HomeActivity，但 `am start` 隐式仍失败 ⇒ TCL 启动链限制，不是包可见性 |
| 加 `QUERY_ALL_PACKAGES`（v3.9.1） | 验证器接受、包可见性生效（日志从 `component unavailable` 变 `not exported`），但隐式解析仍失败 |
| 全局返回键（`input keyevent 4`，连按/双击）弹掉新首页 | 被应用首页完全吞掉，`mCurrentFocus` 和栈都不变 |
| `am start -n .../DetailActivity`（shell 权限） | `not exported from uid 10068` |
| 应用导出的 3 个 receiver（`android.content.movie.search.Action` / `.custom.web.Action` / BOOT_COMPLETED） | 存在但未用于本方案；控件树显示首页**没有**「继续播放」按钮，只有可点击的「历史」入口 |
| 无障碍 UI 自动点击「历史 → 最近记录 → 播放」 | 需开启 `canRetrieveWindowContent`（当前未开），且应用改版即失效；未实施 |

## E. TCL 系统侧线索（只读，未改）

`settings list system` 里与「唤醒回桌面」相关的开关：

```
boot_app_componentname=com.tcl.cyberui/.MainActivity
boot_app_mode=boot_launcher
standby_save_bootsource=1
source_type=source_type_launcher
TVACTIVITY_ONRESUME_FLAG=0
app_auto_boot_auto_management=0
```

历史上尝试写 `boot_app_componentname` 无效并已还原（管理它的 `com.tcl.ttvs` 已禁用）。改这些属于系统级行为，需谨慎评估后再做可逆实验。

## F. 服务不工作时的通用排查顺序

1. `dumpsys package com.wb.mydvresume | grep versionCode` —— 设备到底装的哪一版？
2. `logcat -d -t 20000 -v brief -s MyDvResume:V | grep "service connected"` —— 新代码有没有在跑？
3. `dumpsys accessibility | grep -E "Service\[label|Crashed services"` —— 是否 Bound、有无崩溃；`Crashed services:{}` 才正常。
4. `pidof com.wb.mydvresume` —— 进程是否被 FreezeManager 冻结。
5. `cmd appops get com.wb.mydvresume | grep -E "APP_AUTO_START|APP_ASSOC_START|GET_USAGE_STATS"` 与 `cmd deviceidle whitelist | grep mydvresume` —— 覆盖安装后常被重置。
6. 以上任一缺失 → 重跑 `finalize_resume.py`。
7. `boot_target.py --wake-report` —— 看 `standby class=`、`WAKE via`、`HOME after wake` 时序。

## G. 环境坑

- `adb install` → `INSTALL_FAILED_VERIFICATION_FAILURE`（TCL 签名门），必须走 tcast。
- `input keyevent 26` 注入电源键 → 5555 掉线且唤不醒，**禁止**。
- Java 25 与 D8/R8 不兼容 → `javac --release 8` + 老 `dx`。
- 中文路径下 aapt2 出错 → 源码固定在 `C:\Temp\wbapk`。
- pythonw 黑框 → 脚本里用 `CREATE_NO_WINDOW`。
- 电脑侧守护 / 计划任务已按用户要求**全部停用**，不要重新启动。


## 症状：待机唤醒后打开的是**另一个应用**（v4.1 已修）

现象（2026-11-15 18:51）：待机前在看红果TV，唤醒后服务连续把 myDV 拉到前台；按 HOME 回桌面也会被服务的纠正点拉回。

排查时先看服务日志的这两行：

```
WAKE candidate=<包名> intent=null standby=<包名> fresh=...
WAKE via ... target=com.github.mytv.dv
```

`WAKE class from standby record` / `top=` 显示的是**正确的**待机前页面，但 `target` 却是 myDV —— 这说明问题不在「记住了哪个界面」，而在**目标包无法解析出可启动的 intent**。

核对方法：

```bash
# 白名单与静态组件表是否一一对应
settings get system wb_boot_whitelist
cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LAUNCHER <包名>
```

本例 14 个白名单应用里 `KNOWN_COMPONENTS` 只映射了 13 个，缺的正是后加的红果TV。Android 11 包可见性让 `getLaunchIntentForPackage()` 返回 null，`resolveWakeTarget()` 的 `probe != null` 失败 → 静默回退 `TARGET`。**补组件表 + 改用 SCREEN_OFF 待机记录选目标 + 通用 class 兜底** 后解决；详见 [CHANGELOG.md 的 v4.1 根因](../CHANGELOG.md)。

不要往「任务栈 / SINGLE_TOP / 播放页不导出」方向排查——那是 v4.0 已解决的另一类症状（进应用首页、有声音没画面）。


## 症状：电视装了新应用，待机唤醒却回不到它（v4.2 已修）

**现象**：v4.1 及以前，`wb_boot_whitelist` 是 `boot_target.py --all-apps` 生成的一次性静态快照，`KNOWN_COMPONENTS` 是手工静态表。新装应用既不在白名单、也没有组件映射；Android 11 包可见性又让 `getLaunchIntentForPackage()` 返回 null → `resolveBootIntent()` 返回 null → `resolveWakeTarget()` 静默回退默认 myDV。以前只能连电脑重跑 `--all-apps`，甚至改源码补组件表。

**v4.2 的解法**（自动学习，详见 [CHANGELOG.md 的 v4.2 章节](../CHANGELOG.md) 与 [architecture.md 第 10 节](architecture.md)）：

1. 清单加 `QUERY_ALL_PACKAGES` 打开包可见性（普通权限，v3.9.1 已验证验证器接受；不是 `<queries>`）；
2. 绑定时全量扫描自装应用 + `PACKAGE_ADDED/REPLACED/REMOVED` 增量学习 + `SCREEN_OFF` 兜底重扫；
3. 把每个应用的 launcher 组件缓存进 SharedPreferences，`resolveBootIntent()` 六级解析；
4. `isAllowed()` = 静态白名单 ∪ 运行时自装集合，待机记录与唤醒目标自动覆盖新应用；
5. v4.2.1 收紧到 `FLAG_SYSTEM == 0`，避免把 TCL 的 OTA 更新系统应用误当自装应用拉起系统界面。

**若新应用仍不被恢复，按顺序查**：

```bash
python verify_autolearn.py --follow          # 版本 / 绑定 / userApps / PACKAGE_ADDED / fallback
adb shell "settings get system wb_auto_learn"      # 是否被关成 0
adb shell "settings get system wb_learn_exclude"   # 是否被排除
adb shell "pm list packages -3"                    # 与日志里的 userApps 对照
cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.LEANBACK_LAUNCHER <包名>
```

- `auto-learn scan` 的数量应等于 `pm -3` 减掉服务自身；偏少就查 `SKIP_PKGS` / `wb_learn_exclude`；
- 纯服务型（无 launcher Activity）应用本来就没有界面可恢复；
- 出现 `no launchable component` 说明六级解析全失败，可把包名写进 `wb_boot_whitelist`（静态表路径仍兼容）；
- **冷开机**场景 TCL 还可能要求 `APP_AUTO_START` appops，可选跑一次 `python verify_autolearn.py --allow-autostart` —— 第三方应用无法自行设置该 appops，这是唯一的电脑侧边界。

## 症状：安装完成瞬间闪出「下载失败」，但应用其实装好了（2026-11-15 已修）

**这是推送脚本的收尾造成的假提示，不是安装失败。** 现象：按完「同意」后安装成功，画面上却一闪而过一个「下载失败」提示；核查 `dumpsys package com.wb.mydvresume | grep versionCode` 与设备内 `base.apk` 哈希，新版本已正确装好。

**证据**（2026-11-15 19:22 推送 v4.1 时的电视端 logcat，按顺序）：

```
19:22:22  "GET /MyDvResume.apk HTTP/1.1" 200 -      ← 单次下载，进度 0→39→78→100
19:22:25.176  PACKAGE_ADDED com.wb.mydvresume       ← 安装已成功
19:22:25.199  Session cabc3b4@close isRemove: true
              LocalNetwork: onSessionDisconnect ip: 192.168.1.15   ← PC 主动断开
19:22:25.213  TCastManager: responseCmd...
              Send broadcast status 1 to launcher    ← 闪「下载失败」
19:22:25.243  NanoHTTPD SimpleWebServer IOException: Socket closed
```

**根因**：旧版 `scripts/push_apk.py` 一收到 `stage=5`（或 `installed`）就立刻 `sock.close()` + `httpd.shutdown()` + `return`。而 TCL 多屏互动是在 `PACKAGE_ADDED` **之后**才移除安装业务会话（`onBusinessRemove`）的；PC 抢先断连被 `TCastManager` 判为异常会话中断（`onSessionDisconnect`），于是给 launcher 广播失败状态，弹出那个提示。整个下载/安装链路其实是完整的。

**修复**（只改 PC 端推送脚本，**APK 源码与电视上的版本都不变**）：

1. 新增 `finish()`：安装成功后保持会话，继续发 `150>>` 心跳、HTTP server 继续服务，等电视端主动关会话；最多等 `GRACE_SECONDS = 10` 秒再优雅关闭。
2. 优雅期内把后续 `223` 状态打印为 `late TV state:`，以后若真有 `stage=2` 也能看见，不会被 `sock.close()` 截断。
3. 顺带修正一个逻辑 bug：`stage=2` 原本只 `break` 掉消息 for 循环，仍会卡在当前 URL 直到 300 秒超时；现在用 `attempt_done` 标志真正切到下一个 URL。

本地用 `socketpair()` 模拟验证过两种情形：电视端主动关会话 → 0.3 秒干净退出；电视端无响应 → 超时后也能正常关闭 HTTP server 并返回 0。

**注意**：这个提示与 v3.5 那次「推送失败」不是同一回事，也不要往「TCL 签名门 / HOME 声明 / 多 URL 重试」方向排查——那些会出现 `stage=4` 或 `stage=2`，而这里下载是 200、进度到 100%、`PACKAGE_ADDED` 已发出。

## 症状：推送到电视时看不到应用名称和版本号（v4.3 已修）

**现象**：PC 控制台能看到版本，电视上却只有「多屏互动 / 1 正在发起应用推送，同意后将接收应用并进行安装 / 拒绝 / 同意」，没有应用名、没有版本号。

**这不是脚本没传**：tcast `223>>INSTALL` 帧的第 7 个字段确实是 `versionCode`，label 字段也携带应用名。但 2026-11-15 21:12 的 UI dump 证明 `com.tcl.MultiScreenInteraction_TV` 的确认框是**固定布局 + 固定文案**：只有 `iv_icon`、`tv_title`、`tv_content`、`btn_negative`、`btn_positive`，没有任何应用名 / 版本控件。逐项实测结果：

| 尝试 | 结果 |
| --- | --- |
| 把版本拼进 label | 弹窗文字一字不变 |
| 把版本写进下载文件名 | 弹窗文字一字不变 |
| 把 `sizeMB` 槽位换成自定义文本 | `tv_content` 一字不变 |
| `cmd notification post -t '应用名+版本'` | 通知 importance=3 进通知中心，屏幕无横幅 |
| `cmd statusbar expand-notifications` | 电视不渲染通知面板 |
| `APPLICATION_DETAILS_SETTINGS` | 该系统 Activity 不存在 |

**结论**：协议字段、系统通知都改不动这个弹窗，别再试。**v4.3 的解法**是另画一层 UI —— `push_apk.py` 在发 `INSTALL` 帧前广播 `PUSH_BANNER`，无障碍服务用 `TYPE_ACCESSIBILITY_OVERLAY` 在左下角显示应用名 + `versionName` + `versionCode`，45 秒后自动消失；弹窗在右上角，两者零重叠，遥控器按键不受影响。详见 [build-and-push.md 版本显示章节](build-and-push.md) 与 [architecture.md 第 11 节](architecture.md)。

**若横幅没出现，按顺序查**：

```bash
adb shell dumpsys accessibility | grep -A3 "Bound services"     # 服务必须 Bound
adb shell logcat -d -s MyDvResume:V | grep "banner shown"       # 是否收到广播并绘制
python push_apk.py --banner-only                                # 只画横幅、不安装
```

- 推送脚本打印 `TV banner: skipped` → 电视上还是 v4.2.1（旧服务无 receiver），**下一次**推送才生效；
- 打印 `NOT confirmed in logcat` → 查无障碍绑定，或 `am broadcast` 是否被系统拦下；
- 日志校验不要用 `logcat -t N -s TAG`（先按行数截断再过滤 tag，会漏掉横幅日志）；
- `--hide-banner` 可立即收起横幅。
