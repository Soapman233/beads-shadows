# 豆影 Android 本地调试壳

Android 壳使用系统 WebView 打开构建时指定的豆影来源，提供页面导航、触屏制作及文件选择。项目、账户与制作状态仍经既有豆影接口同步。壳当前采用浏览器下载作为图纸导出的工作流。

使用 JDK 17、Gradle 8.9、Android SDK 平台 35，从本目录执行：

```powershell
gradle assembleDebug '-PbeadsOrigin=http://127.0.0.1:8784'
adb reverse tcp:8784 tcp:8784
adb install app/build/outputs/apk/debug/app-debug.apk
```

启动桌面端的独立豆影实例后，使用已连接的测试设备或模拟器。远端配置传入本人控制的有效 HTTPS 来源。壳只允许固定来源的导航，不安装 JavaScript 原生桥。Android 系统将应用与浏览器的会话分别保存。

本机检查找到 JDK，未发现 Android SDK、Gradle 或已配置模拟器。已提供可构建工程与命令。APK 构建、安装、上传、触控与跨设备续做需要在有 SDK 和设备的环境验证。

[Android Gradle Plugin 8.7 兼容表](https://developer.android.com/build/releases/agp-8-7-0-release-notes) · [Android WebView](https://developer.android.com/develop/ui/views/layout/webapps/webview)
