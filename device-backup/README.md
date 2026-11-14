# 设备状态快照

做 cleanyourtv 精简、改系统设置、禁用系统应用**之前**采集的原始状态，用于审计和一键还原。全部是文本，来自 `adb shell` 的 `pm list packages` / `settings list` / `getprop` / `dumpsys` 输出。

| 文件 | 内容 |
| --- | --- |
| `packages_all.txt` / `packages_system.txt` / `packages_thirdparty*.txt` | 精简前后全部包名 |
| `packages_disabled_before*.txt` / `packages_disabled_after.txt` | 被 `pm disable-user` 禁用的包（前后对照，共 29 个） |
| `settings_system_all.txt` / `settings_secure_all.txt` / `settings_global_all.txt` | 三类系统设置完整 dump |
| `config_all.txt` | TCL 厂商配置表 |
| `getprop.txt` | 全部系统属性 |
| `debloat_official.txt` | `Gathin23/cleanyourtv` 官方精简清单（带注释） |
| `accessibility_before.txt` / `home_before*.txt` | 改动前的无障碍服务与默认桌面 |
| `screensaver_after.txt` / `standby_before_harden.txt` / `standby_harden_state.json` | 屏保按键与待机加固状态 |
| `boot_app_original.json` | 开机启动项的原始值（写入尝试失败后已还原） |
| `resume_watch.log` | 早期 PC 侧守护的一次运行日志（该方案已废弃） |

## 脱敏

`sync_and_push.py` 对以下文件做替换后再入库：

- `getprop.txt`：`ro.boot.serialno` / `ro.serialno` → `<REDACTED>`
- `config_all.txt`、`settings_secure_all.txt`：密码类字段、任何 `ghp_` / `github_pat_` 形态的令牌 → `<REDACTED>`

其余文件只含包名、设置项与系统属性，不含个人数据。仓库是公开的，请不要把任何凭据粘贴进来。

## 还原

```bash
cd E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup
python restore_tcl.py --status   # 查看可还原项
python restore_tcl.py --this     # 还原本次改动
python restore_tcl.py --all      # 还原全部
```

详细命令与禁用清单见 [docs/adb-cheatsheet.md](../docs/adb-cheatsheet.md) 与 [docs/device-setup.md](../docs/device-setup.md)。
