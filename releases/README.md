# 已签名 APK 归档

`sync_and_push.py` 每次同步时，会把 `C:\Temp\wbapk\MyDvResume.apk` 复制成
`MyDvResume-vc<versionCode>.apk`。**不覆盖旧文件**，所以每升一次版本就多留一份，形成可回溯的二进制历史。

| 文件 | 版本代号 | versionCode / Name | 说明 |
| --- | --- | --- | --- |
| `MyDvResume-vc16.apk` | v4.0 | 16 / 3.0 | 显式组件 + `RESET_TASK_IF_NEEDED` 任务栈复用，sha256 `bdc3c83c…85d3` |
| `MyDvResume-vc17.apk` | v4.1 | 17 / 3.1 | **当前版本**：唤醒目标改用 SCREEN_OFF 待机记录 + 补全组件表，sha256 `bf40c492…1c5` |

早期版本（v1 ~ v3.9.1）的成品 APK 已被本地构建覆盖，只保留了源码快照在 [`history/`](../history/README.md)；其中 `history/v1-initial/MyDvResume-v1.apk` 是最早那版的成品。

> 安装提示：这些 APK **不能**用 `adb install`，必须走 6553 tcast 多屏互动推送，并在电视端确认；覆盖安装后要重跑 `finalize_resume.py`。见 [docs/build-and-push.md](../docs/build-and-push.md)。
>
> 签名私钥不在本仓库，重新用源码构建得到的 APK 签名不同，无法覆盖安装电视上现有服务。
