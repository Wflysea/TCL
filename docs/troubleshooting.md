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
