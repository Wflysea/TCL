# APK 源码

`com.wb.mydvresume` —— 一个没有界面、没有启动图标的 AccessibilityService。

## 文件

| 文件 | 说明 |
| --- | --- |
| `AndroidManifest.xml` | 当前 `versionCode 16 / versionName 3.0`。三项权限：`SYSTEM_ALERT_WINDOW`、`PACKAGE_USAGE_STATS`、`KILL_BACKGROUND_PROCESSES`；service 用 `BIND_ACCESSIBILITY_SERVICE` 保护并 `exported=true`。v4.0 已移除 v3.9.1 临时加的 `QUERY_ALL_PACKAGES` |
| `src/com/wb/mydvresume/ResumeService.java` | 全部逻辑：唤醒检测、任务栈恢复、冷启动目标、白名单、myDV 静音、系统设置读写 |
| `res/xml/resume_config.xml` | 无障碍服务配置（`canRetrieveWindowContent` 当前**未**开启） |
| `res/values/strings.xml` | 服务标签 / 描述（电视上显示为「myDV Resume」） |
| `build_apk.py` | 零依赖构建+签名脚本 |

## 构建

本机固定路径 `C:\Temp\wbapk`（脚本内硬编码），工具链在 `C:\Temp\wbapk\tools`：

```bash
cd C:\Temp\wbapk
python build_apk.py
```

流程：`aapt2 compile/link` → `javac --release 8` → `dx` → 把 `classes.dex` 塞进 APK → `zipalign` → `keytool` 生成密钥（幂等）→ `apksigner sign` → `apksigner verify`。

注意：

- JDK 25 下 D8/R8 会 NPE 崩溃，所以刻意用 `--release 8` 编译出 class version 52 再走老 `dx`。
- 源码路径曾因中文路径导致 aapt2 出错，故工作目录固定在纯 ASCII 的 `C:\Temp\wbapk`。
- **清单里绝对不要加** HOME / LAUNCHER / LEANBACK_LAUNCHER / `<queries>`，会触发 TCL 安装签名门。

## 签名凭据（不入库）

| 项 | 本机位置 | 是否入库 |
| --- | --- | --- |
| 私钥 `mydvresume.jks` | `C:\Temp\wbapk\mydvresume.jks` | ❌ |
| 口令 | `C:\Temp\wbapk\.keystore_pass`（单行）或环境变量 `MYDV_KEYSTORE_PASSWORD` / `MYDV_KEYSTORE_PASS_FILE` | ❌ |

`build_apk.py` 从上述本地文件/环境变量读口令，源码里没有明文。因为这是**公开仓库**：

- 用仓库源码直接签名会得到**不同签名**，无法覆盖安装电视上现有的服务；
- 私钥只在原开发机保留。换机器时请自行 `keytool -genkeypair` 生成新证书，并先卸载旧服务再安装；
- 任何情况下都不要把 `.jks`、口令文件或 GitHub PAT 提交进来。

## 推送

构建完成后不要用 `adb install`，走多屏互动推送（详见 [docs/build-and-push.md](../docs/build-and-push.md)）：

```bash
cd E:\WorkBuddy\闲聊\_tmp\tcl75v8l_backup
python push_apk.py      # 电视端按「右 → 同意」
python finalize_resume.py   # 覆盖安装后必须重绑
```
