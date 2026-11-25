# 多用户平台验收索引

2026-11-24，使用现有 MySQL 8.4.8 的隔离实例、Python 3.12 环境和工作区合成素材。本地演示入口为 `http://127.0.0.1:8784/`，启用重绘、支付模拟与本地开发收件箱。接口测试在另一个库和临时端口运行。最终集成测试 12 项通过，前端测试 33 项通过，生产构建通过。

|范围|实现入口|验收证据|
|---|---|---|
|G0、P0 多用户和项目|auth.py、projects.py、catalog.py、CloudProjects.vue、storage.ts|真实迁移、资源隔离、409 竞争保护、浏览器注册与项目同步恢复|
|A14 数据恢复|platform_api/backup.py、mysql_backup_workflow.py|空库恢复后登录并读取原图、掩码和同一版本|
|P1 库存、制作、发布|inventory.py、builds.py、publications.py、InventoryPanel.vue、Workshop.vue、PatternLibrary.vue|并发扣减与幂等、加权制作进度、上架和下载权限、公开预览字段裁剪|
|P2 重绘、限色和二创|ai_jobs.py、extensions.py、AIJobs.vue、数据库色卡 Worker 路径|真实 MySQL 模拟任务和额度；库存、候选替色、私有成品和独立二创溯源|
|X1 社区、实时协作|social.py、notifications.py、collab.py、CommunityInbox.vue、CollaborationPanel.vue|评论、私信、双 WebSocket 顺序、重连、撤权、安全撤销和整图租约，更新后保留旧协作图纸|
|X2 商城与会员|commerce.py、payment_providers.py、MaterialShop.vue|本地模拟；库存预留、服务器价格、退款、会员发放和撤销|
|X3 PWA、插件、找回|offline-worker.js、extensions/chromium、account_tools.py、mobile/android|构建及离线缓存隔离、MV3 语法、邮箱本地投递、单次令牌和账号关闭|
|Q04–Q07|实验脚本、论文与测试记录|18图基线、6图消融、8并发读取、真人与实物测试表|

生产浏览器复验选择“图纸库 → 打开几何模板”，生成了 16×16、144 颗、3 色的编辑项目。新建合成账号后复制游客草稿，登记板块完成，再刷新并打开制作记录，进度仍为 144/144。截图为仓库外 `output/mysql-workshop-8784.jpg`。

## 2026-11-25 收尾

8784 使用本轮生产构建。真实 MySQL 定向验证通过 SAM 2.1 Tiny 双账号轮换、关闭账号恢复、统计时间窗口及本地模拟重绘结算。当前前端 34 项测试通过。独立 Chromium 在 390×844 视口实际完成制作色号选择和板块操作，观测进度 144/144。桌面 CPU 基准和带 50 mm 标尺的 32×32 样张已生成并核对。

| 尚待验收 | 最小条件与入口 |
|---|---|
| A08、A12、F02 浏览器离线 | Chromium 已证实断网冷启动、缓存色卡可选和原账号恢复。打开测试图纸后交互连接超时。还需实测离线改格后手动同步、版本冲突、未缓存色卡回退及 Service Worker 实际换版。 |
| B05、B11、C04、F01 界面与设备 | 已证实窄屏操作和服务端续做。还需设备间续做、后台页面/API 对照、重绘的页面采用与取消、PWA 安装和实际触屏。 |
| C05 百炼 | 提供本机配置的工作空间与模型权限，指定可传给百炼的样例和试跑预算。 |
| E05 支付渠道 | 指定测试渠道，提供沙箱商户和获准的回调环境。 |
| F06 SMTP | 在隔离环境配置测试 SMTP 和获准的收件邮箱。 |
| F03–F05 浏览器插件与 Android | 在独立 Chromium 配置文件中装载插件并测试右键菜单。Android 需要 Gradle、SDK 35、Build Tools 和专用设备。现有 MuMu Android 12 处于停止状态。 |
| Q06、Q07、Q09 毕设实测 | 提供轻薄本、5–8 名自愿参与者、匹配色号的豆板/豆和打印条件、学校模板。可先用现成的复现命令、记录空表与样张。 |
| C11 账号保留 | 已验证本人邮箱验证码和管理员协同恢复。正式保留期、共享引用处理及物理清理需由项目所有者确定。 |

[任务账本](full-platform-progress.md) · [真实测试与命令](full-platform-testing.md) · [权限矩阵](platform-access-matrix.md) · [样张与性能复现](human-validation.md) · [对照实验](kmeans-lab-comparison.md) · [限色消融](platform-ablation.md)
