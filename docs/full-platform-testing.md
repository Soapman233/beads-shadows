# 多用户平台验证记录

## 真实环境

使用本机已安装的 MySQL Community Server 8.4.8，单独初始化工作区外层 `tmp/beads-full-platform-mysql/data`，绑定 `127.0.0.1:13306`。此实例使用独立账号及开发、测试库。没有读取原有 MySQL 数据目录。应用复用现有 Python 3.12 环境，测试服务每次使用独立临时端口和资产目录，测试输入为脚本生成的几何图。

测试机器的连接文件在仓库外，本文件只记录加载方式。需在能够访问本机端口的终端执行。任何其他机器可先创建同名隔离测试库并设置 `BEAD_DATABASE_URL`。

```powershell
$env:BEAD_DATABASE_URL = (Get-Content -LiteralPath '..\tmp\beads-full-platform-mysql\connection.json' -Raw | ConvertFrom-Json).test
$python = (Resolve-Path '..\mvp\backend\.venv\Scripts\python.exe').Path
Push-Location backend
try { & $python -m alembic upgrade head } finally { Pop-Location }
& $python tests/mysql_platform_test.py
```

脚本只接受回环地址上的 `beads_platform_test` 库。每个场景启动自己的进程和临时端口，保留原有登录限流。测试写入合成账号、图纸和库存等数据，并在被忽略的 `tmp/mysql-platform-tests` 下保留诊断日志及合成资产，不触碰应用草稿。测试服务禁用 SAM 和外部 AI，使用本地重绘、模拟支付和开发收件箱。

## 已执行

最终构建在 `20261124_structure_lease` 迁移对应版本通过。完整 MySQL 集成套件运行 12 项，通过 12 项，耗时 25.654 秒。前端已有测试运行 33 项并全部通过。

在同一隔离测试库另用四个合成文件验证资产维护。一份无引用登记资产和一份丢失数据库登记的暂存文件被列出。预览不改数据，隔离操作迁移两份候选，释放一条未引用的记录，保留旧项目引用和新文件。

2026-11-24 在 `20261118_account_tools` 迁移上完整执行 `tests/mysql_platform_test.py`，11 项通过，耗时 28.332 秒。

|任务|检查|实际结果|
|---|---|---|
|G0-02、G0-04|用 MySQL 客户端查询 VERSION 和 DATABASE，执行 Alembic 迁移|8.4.8，隔离库 `beads_platform_test`。空库迁移成功，后追加迁移到 `20261118_inventory`|
|A02–A07、A09|真实 MySQL 和本地 HTTP，执行 `MySQLPlatformTest.test_private_assets_idempotent_import_conflict_and_restore` 与 `MySQLPlatformTest.test_session_revoke_and_cpu_segmentation_partition`|通过。A/B 图片、项目、历史和资源引用隔离。重试导入同一 ID，仅生成一个项目。同时保存同一版本得到 200 和 409，版本可恢复、回收。无效 PNG、非法色号和无会话校验的操作被拒绝。退出、改密撤销会话|
|A05|真实 CPU GrabCut 处理 A 宽矩形、B 窄矩形、再处理 A|通过。检查中心和边缘掩码值，两次 A 掩码直接比较一致。跨账号分割请求被拒绝|
|A08|在 frontend 运行 `node_modules\.bin\tsx.cmd --test ../tests/storage.test.ts`|8 项通过，包含同 ID 的两个账号缓存分别保留源图、元数据和远端版本。不视为浏览器离线/跨设备验收|
|A01、A06、A08|隔离浏览器来源 127.0.0.1:5196，连接现有 MySQL 测试库|注册甲→生成几何样例 32×32、992颗、7色→同步出现版本1→切换乙显示没有项目→切回甲重新打开并刷新恢复原图纸。未见控制台 error。截图位于工作区 output/mysql-p0-ui-proof.jpg|
|A02、A03、A10、A11、A13|真实 MySQL 和 HTTP，执行 `MySQLPlatformTest.test_palette_publication_identity_audit_and_account_freeze`|通过。正常账号访问管理接口返回403，旧页面身份不一致返回409。拒绝重复色号和非法HEX，草稿不可公开访问。发布新版保留已退役旧版的色值，只有明确选择的色号沿用库存身份。冻结使原会话失效，解冻后仍须重新登录，审计记录冻结和解冻两项|
|B01–B03|真实 MySQL 和 HTTP，执行 `MySQLPlatformTest.test_inventory_atomic_import_concurrent_issue_and_versioned_shortage`|通过。CSV 导入幂等，无效色号整批拒绝。入库5颗后并发各领4颗，返回201/409，余1颗且仅含1条领用流水。重试不重复扣减，同编号改数量返回409。2颗白豆加25%余量为3颗、缺2颗，估价0.50。空格不计，未填价格显示为空|
|B04、B06–B09、B12|MySQL 8.4.8 与真实 HTTP，执行 `MySQLPlatformTest.test_workshop_weighted_progress_and_moderated_publications`|通过。同一合成图纸版本需4颗、库存2颗、缺2颗，补2颗后领用4颗，库存为0，领用记录指向该版本。再执行 **制作 → 提交发布 → 审核 → 另一账号收藏**。两个有效块分别为3颗与1颗，空块404，旧revision返回409，改图纸不影响原版本制作和发布。公开详情不返回原图、掩码、工程标识或cells。未审/下架后详情、预览及下载均404，发布后图片预览可用，禁止下载时返回403。收藏重复提交只计一次，举报可审核，下架后收藏列表隐藏。新增同项目链路定向通过（3.212秒）|
|C01–C03（模拟）|2026-11-24，同一 MySQL 与真实 HTTP，执行 `MySQLPlatformTest.test_simulated_ai_job_is_owned_consumed_once_and_readable`|通过。普通用户不可发额度，授额和提交均幂等。服务商预期不匹配返回409，B无法提交A的原图、取消A的任务或获取A的输出。切换登录会话后可查询完成结果，单次额度仅结算一次，输出为64×64 PNG。未发起百炼请求|
|C06–C10|2026-11-24，同一 MySQL 与真实 HTTP，执行 `MySQLPlatformTest.test_extensions_stock_completion_and_remix_provenance`|通过。正库存仅本人可见，替代建议保留色卡约束且锁色拒绝。未完成制作不能保存成品记录，源图不可作为成品照片，正确成品资料及照片保持私有。难度接口返回确定的豆数、色数与孤立格。二创可追溯且重试不重复创建，私有色卡说明、源图及掩码均未复制，撤回后拒绝新的二创|
|D01–D03|2026-11-24，同一 MySQL 与真实 HTTP，执行 `MySQLPlatformTest.test_community_comments_notices_private_messages_and_blocks`|通过。只有公开作品可评论，作者可删除本人评论，通知限收件人查看和标已读。私信限双方读取，同请求重试只写一条。屏蔽阻断双方发送，解除后恢复。全部消息均发给隔离库中的合成账号|
|D04–D06|2026-11-24，真实 MySQL、HTTP 和两个本地 WebSocket，执行 `MySQLPlatformTest.test_collaboration_two_live_sockets_and_revision_isolation`|通过。游客和其他来源握手被拒，viewer不能写，撤销后已有连接收到4404，重新邀请为编辑者后双方能收到有序操作。重复编辑不重复入库，旧操作撤销不能覆盖他人后续编辑，重连取得最新快照，仅作者能按当前序号提交，原图保留|
|D06 结构租约|真实 MySQL 8.4.8、`20261124_structure_lease` 迁移和 HTTP，执行 `MySQLPlatformTest.test_structure_lease_expires_and_preserves_previous_room`|通过。有活动房间时，常规保存或恢复返回409。仅所有者可申请租约，且仅签发会话能提交。同一请求重放结果一致，其他租约或锁定期间协作写入被拒。只在隔离库内将该合成租约到期时间设为过去，验证过期提交拒绝、格子写入恢复，重新获取后保存新尺寸，旧房间快照保持可读|
|E01–E04、E06–E08（模拟）|2026-11-24，Developer在真实 MySQL 检查订单库存竞争、预留释放、状态、幂等、会员生效与撤销。HTTP补测 `MySQLPlatformTest.test_simulated_shop_order_and_membership_owner_boundaries`|通过。匿名订单401，普通账号管理403，客户端提交价格被拒。订单金额依数据库套餐价，B不能支付A的订单或看A的权益。模拟支付重试仅产出一项会员权益，AI次数独立。真实支付渠道、付款、退款及发货未验收|
|C11、F06（本地收件箱）|真实 MySQL 和 HTTP，执行 `MySQLPlatformTest.test_local_recovery_one_use_and_private_export_close`|通过。邮箱与重置验证码只写开发收件箱，不出现在测试日志。绑定和找回码只能用一次，重置撤销会话，旧密码无效。A导出包含本人图纸和图片，B看不到。主动关闭拒绝旧会话和登录，作品退出公开目录，详情、预览、下载均404，普通管理员解冻拒绝，私有项目和图片记录仍保留。SMTP、账号保留期限和最终清理未验收|
|A14、Q02部分|MySQL 8.4.8 独立备份演练实例 127.0.0.1:13307，`tests/mysql_backup_workflow.py`|源服务停止后生成 mysql dump 与两份资产，恢复到空目标库。目标服务登录及读取同版本项目成功，原图及掩码下载均200。初次脚本末尾把 RGBA 掩码像素当灰度比较，修正测试后直接复核两份现场恢复 PNG 与源资产字节值一致|
|Q04|运行 `experiments/run-kmeans-lab.ts`|18个公开输入同条件用色及掩码检查通过。逐图及负结果见 [实验报告](kmeans-lab-comparison.md)|
|本地旧模式|既有 `tests/backend_test.py`|5 项通过，包括真实 CPU GrabCut 与规范化。SAM 部分为替身，未重跑真实模型|

## 待验证

浏览器断网重连、真实外部服务、真人与实体拼豆仍须另行验收。WebSocket 重连已使用网络客户端验证，浏览器离线体验单列。
