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

真实百炼、支付渠道和 SMTP 尚待服务配置。浏览器扩展安装、浏览器断网流程、移动触屏与 Android APK、轻薄本及真人实物尚待实测。当前环境没有 Android SDK 和 Gradle。账号恢复及物理清理的正式保留策略需结合实际部署确定。

[任务账本](full-platform-progress.md) · [真实测试与命令](full-platform-testing.md) · [对照实验](kmeans-lab-comparison.md) · [限色消融](platform-ablation.md)
