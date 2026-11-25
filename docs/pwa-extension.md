# 移动端与浏览器导入

## PWA

- 使用 `npm.cmd run build` 构建前端，再通过 FastAPI 服务打开豆影。开发服务器使用即时编译，只有生产构建注册 Service Worker。
- 支持的浏览器可从地址栏或菜单选择安装豆影。安装依赖浏览器支持和安全上下文，本机测试可使用 `localhost` 或 `127.0.0.1`。手机要访问另一台设备上的服务，需要已有的 HTTPS 地址。
- 首次在线加载完成后，安装的离线缓存包含应用壳、生成 Worker、构建样式和应用图标。Service Worker 仅按构建生成的静态清单缓存，包含用户身份、图纸、素材、订单及 AI 的 API 路径会直接走网络。账号缓存仍由工作区按账户分开处理。离线冷启动进入游客工作区，在线时通过服务端会话恢复账号身份。
- 在线打开首页优先使用服务器提供的版本。浏览器关闭仍在使用旧版本的页面后，可启用新安装的 Service Worker 并清除旧应用壳缓存。
- 手机端制作页支持触控选格与选板块。完成标记需要在线写入账户记录，服务端保存成功后才更新完成进度。
- 已打开的账号工作区断线后继续按账号保存本机草稿并提示手动同步。离线冷启动显示游客工作区。恢复连接后，点击「恢复账号工作区」会刷新核对服务器会话再切回原账号。近期读取的公开数据库色卡保留在独立本机缓存。未缓存的历史色卡版本可改用内置色卡重新生成，已保存图纸继续按原快照显示。

## Chromium 插件

在 Chrome 或 Edge 的扩展管理页打开开发者模式，选择「加载已解压的扩展程序」，选择本工程的 `extensions/chromium`。在扩展菜单打开「豆影导入设置」，填入当前运行的豆影根地址，保存并授权该站点。例如验证环境用 `http://127.0.0.1:8780`，实际端口请按启动输出填写。

在来源页图片上点击右键并选择「导入豆影」。插件只读取这一次选中的 PNG/JPG，大小上限 10 MiB。它按来源页面的正常访问规则读取图片，读取时省略 Cookie，遇到跨域、授权或跳转限制时可通过普通文件导入。插件会打开所配置的豆影页面，显示待导入图片，由用户确认采用。

设置中只保存目标服务地址和当次状态。图像内容不写扩展存储，只发送给用户选择的目标页面。来源信息仅带来源站点的 origin，不带具体页面地址、查询参数或标题。插件不在后台监视页面，也不下载到第三方服务器。

## 接收协议与验证

通过目标页面 `window.postMessage`，协议版本为 `1`。插件发送 `bead-extension:probe` 携带 `requestId`，页面确认已准备后回 `bead-extension:ready`。随后插件只发送一次 `bead-extension:import`，携带同一编号、`File` 和 `sourceOrigin`。页面校验来源、文件类型和大小后保留待确认文件，并回 `bead-extension:received`。接收回执表示进入确认流程，采用后才进入正常导入。

本地验证覆盖生产构建、静态清单及扩展脚本语法。从生成的 Worker 在 Node 隔离环境检查了根页面离线回退、生成脚本在缓存清单内，以及私有直达 API 绕过缓存。浏览器安装 PWA、移动真机和正常装载扩展的流程需要浏览器实测，Node 检查不作为这些项目的验收证据。

技术参考：[Chrome activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab) · [Chrome Scripting API](https://developer.chrome.com/docs/extensions/reference/api/scripting) · [Chrome 主机匹配模式](https://developer.chrome.com/docs/extensions/develop/concepts/match-patterns)。
