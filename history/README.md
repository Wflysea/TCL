# 历史源码快照

用于对照排查「哪个改动把待机续播弄坏了」。这些都是**当时完整源码的字节级副本**，不是重新整理的摘要。

| 目录 | 来源文件（本机 `C:\Temp\wbapk`） | 版本 |
| --- | --- | --- |
| `v1-initial/` | `_tmp/tcl75v8l_backup/apk_source/` 的 manifest + res + 早期成品 APK | 最初的 AccessibilityService（事件不派发） |
| `v3.6/` | `v36_ResumeService.java` | 用户实测可用的基准版（vc10 / 1.9） |
| `v3.9.1/` | `v391_ResumeService.java`、`v391_AndroidManifest.xml` | 加了 `QUERY_ALL_PACKAGES` 的隐式 launcher intent 版（vc14 / 2.3） |
| `v3.10/` | `v310_ResumeService.java`、`v310_AndroidManifest.xml` | 完整回退到 v3.6 行为（vc15 / 2.4） |
| `v4.0/` | `v40_ResumeService.java`、`v40_AndroidManifest.xml` | 任务栈复用方案（vc16 / 3.0），用户实测通过 |
| `v4.1/` | `v41_ResumeService.java`、`v41_AndroidManifest.xml` | 待机记录优先选目标 + 补红果TV 组件（vc17 / 3.1） |
| `v4.2.1/` | `v421_ResumeService.java`、`v421_AndroidManifest.xml` | 自动学习白名单最终版（vc19 / 3.3），v4.3 横幅改造前的基准 |
| `v4.3/` | `v43_ResumeService.java`、`v43_AndroidManifest.xml` | 电视端推送横幅版（vc20 / 3.4），v4.4 移除横幅 + 单次启动前的基准 |

当前版本源码在 [`apk/`](../apk/README.md)。

> `apk_source/build_apk.py`（早期构建脚本）里含明文签名口令，**故意没有收录**；`v1-initial/` 只保留了 manifest、资源与成品 APK。
