# 电视侧配置与还原

这一节记录「软件之外的电视环境」：精简、系统应用禁用、系统设置与还原点。所有改动都是可逆的，操作前快照在 [`device-backup/`](../device-backup/README.md)。

## 1. cleanyourtv

`Gathin23/cleanyourtv` **不是一个 APK**，而是一份官方精简清单 + 桌面工作流。在这台电视上落地的方式是：按 [`debloat_official.txt`](../device-backup/debloat_official.txt) 用 `pm disable-user` 禁用不需要的系统包，而不是卸载或刷机。

结果：共 **29 个禁用包**，全部纳入 `restore_tcl.py` 的撤销范围。禁用前后对照见
`packages_disabled_before.txt` / `packages_disabled_after.txt`。

按用户要求额外禁用：

```bash
adb shell "pm disable-user com.tcl.guard"        # 电视卫士（会清后台）
adb shell "pm disable-user com.tcl.appmarket2"   # 应用商店
```

OTA 保持禁用状态，不做降级刷包。

## 2. 屏保与按键

精简过程中屏保按键被改坏过，已按 `screensaver_after.txt` 记录的原始值修复。改动前的默认桌面、无障碍服务分别留在 `home_before*.txt`、`accessibility_before.txt`。

## 3. myDV

升级到官方 **2.3.44**（`update_mydv.py --check / --upgrade / --install-local`）。期间遇到 GitHub 大文件下载被截断，最终用本地残包校验后安装；设备上确认版本后才继续。

`com.github.mytv.dv` 关机再开机后仍能听到声音，是本项目「待机唤醒只有声音没画面」问题的起点。

## 4. 厂家远控审计

`audit_remote.py` 负责审计厂家远程控制/远程协助相关的组件与服务，输出并入 `device-backup/` 的 `packages_*` / `settings_*` / `config_all.txt` 快照。审计结论与禁用项都以「可逆设置」为原则处理，没有删除系统文件、没有刷机。

## 5. 「待机接着播」清单（用户要求长期保持）

1. **只用遥控器电源键待机／唤醒**，不要用 ADB 注入电源键（会掉线且唤不醒）。
2. **别让电视卫士清后台**：`com.tcl.guard` 保持禁用，服务与目标播放器在电池白名单里。
3. **别降级刷包**，OTA 保持禁用。
4. **升级固件后复查**：系统设置、appops、电池白名单、无障碍绑定都可能被重置，重跑 `finalize_resume.py` + `boot_target.py --status`。
5. **万一断电后想自动打开 myDV**：冷启动目标是 `wb_boot_target`（默认 myDV）；白名单内才会记忆上次应用，否则回退默认。
6. 每次覆盖安装 APK 后重跑 `finalize_resume.py`，然后跑一遍核查清单。

## 6. 已取消的方案

- **PC 侧守护进程 / 计划任务**：用户明确要求「脱离电脑」，已取消并停用（`Disable-ScheduledTask`），**不要重新启动**。全部逻辑都在电视端的 AccessibilityService。
- 内容提供者写入、`set-home-activity`、`boot_app_componentname` 等尝试均无效并已还原，记录在项目日志与 `boot_app_original.json`。

## 7. 还原

```bash
cd E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup
python restore_tcl.py --status   # 列出可还原项
python restore_tcl.py --this     # 还原本次改动
python restore_tcl.py --all      # 全部还原
python uninstall_resume.py       # 卸载服务（如需彻底回退）
```

单项恢复：`adb shell "pm enable <包名>"`；撤销电池白名单：`adb shell "cmd deviceidle whitelist -<包名>"`。
