# MySQL 多用户模式启动与管理

当前工作区的独立演示入口为 [本机 8784](http://127.0.0.1:8784/)。测试数据均为合成账号和样例。可从登录页注册自己的演示账号，管理员使用下方的交互式命令创建。现有浏览器草稿按来源保留，跨端口可通过项目 JSON 导入，登录后也可复制当前来源的游客草稿。

## 配置本地数据库

本轮隔离环境使用 MySQL Community Server 8.4.8。准备一个空库、独立数据库账号与 `utf8mb4` 编码。开发库和测试库要分开。运行账号连接 MySQL 时只授予本库所需权限，部署时可将建表迁移账号与应用读写账号分开。

在现有 Python 环境安装 `backend/requirements.txt` 中的新增依赖。使用 `uv` 管理且未安装 pip 的环境可以运行：

```powershell
$beadPython = (Resolve-Path '..\mvp\backend\.venv\Scripts\python.exe').Path
uv pip install --python $beadPython -r backend/requirements.txt
```

按你的 Python 环境调整路径。项目内安装的环境可使用 `backend\.venv\Scripts\python.exe`。

在启动服务的终端设置 `BEAD_DATABASE_URL`。格式为 `mysql+pymysql://<账号>:<编码后的密码>@127.0.0.1:<端口>/<专用库>`。连接串包含数据库密码，仅保存在本机环境配置。密码内的 `@`、`#` 等 URL 特殊字符须做百分号编码。用同一终端迁移并启动：

```powershell
Push-Location backend
& $beadPython -m alembic upgrade head
& $beadPython -m alembic current
& $beadPython -m platform_api.create_admin bead-admin
Pop-Location
.\scripts\start.ps1 -Cpu -Port 8780 -PythonPath $beadPython
```

管理员创建命令在终端交互输入密码。用户名按 NFKC 和大小写统一后判重，允许 3–32 位英文字母、数字和 `. _ -`；密码长度为 10–128 字符。注册端点只能创建普通账号。

前端和服务同源部署可直接使用会话 Cookie。若为开发代理配置了独立公开入口，设置 `BEAD_WEB_ORIGIN` 为浏览器实际使用的协议、域名和端口。HTTPS 部署设置 `BEAD_COOKIE_SECURE=1`。测试多个前端时，按浏览器配置文件隔离 Cookie；端口只隔离 IndexedDB 等 origin 数据。

清空 `BEAD_DATABASE_URL` 并重启可恢复游客本地模式。`.env.example` 是示例，启动脚本仅读取运行环境。

## 账户和色卡接口

- 注册或登录后，`/api/auth/me` 返回当前账号及 CSRF token。退出、修改密码、编辑资料等已认证的写请求携带 `X-CSRF-Token`。账号界面可另带 `X-Bead-Account`，服务端会拒绝与当前 Cookie 身份不符的旧标签请求。
- 管理员可冻结普通账号并撤销该账号会话。`/api/admin/audit` 记录操作人、动作、目标及原因。登录限流以进程内客户端地址为粒度，供单机模式使用，公网多进程部署应增设共享限流。
- 先建品牌、系列与规格，再上传 CSV。色卡 CSV 支持 `code,hex,material`，材质列可选，允许留空表示未知。来源与数据许可单独登记。
- 差异预览列出新增、移除及变更。明确提供 `reuseColorCodes` 时，匹配到上一发布版本同色号的稳定库存身份。确认前请核对是否仍为同种实物豆；说明不清时生成新的颜色身份。
- 发布新版本时旧版本同时退役。旧版仍可由版本 ID 查询，用于恢复历史项目；选色表只列当前发布版本。

## 库存接口与数据

`inventory_items` 保存本人余量及单颗价格，`inventory_movements` 保存有符号的入库、领用、退回和损耗流水，`inventory_requests` 保存请求编号和原操作结果。CSV 支持 `code,quantity,unitPrice`，数量按颗，价格可留空。手工操作可给 `piecesPerPack`，此时 `quantity` 按包数换算。重复提交使用同一个请求编号。

材料清单使用保存的图纸版本及其色卡快照。只有对应数据库色卡版本、色号和 HEX 完全匹配才查库存。旧项目或未知颜色显示待匹配，材料清单读取不会扣减库存。库存写事务先锁本人用户记录，再校验数量并提交流水，避免竞争和重复领用。

## 制作与公开图纸接口

- `builds` 引用不可变图纸版本。`build_blocks` 保存每块有效豆数与完成标记。进度用已完成豆数计算，空板块无记录。更新时检查制作记录 revision。
- `publications` 保留一份经过字段筛选的网格快照与审核状态。公开详情只含网格、颜色、展示和统计。下载由公开状态与作者设置决定。查看模式能读取展示数据，下载权限控制平台的下载入口。
- `favorites` 的联合主键令收藏幂等。`publication_reports` 记录独立举报和处理状态。审核、下架、处理记录进入 `audit_logs`。
- `/api/admin/overview` 返回当前账号、项目、待审核与待处理举报统计，并按 `days` 汇总近期新增账号、材料操作和仍公开的作品。统计时间用 UTC。

## 模拟与外部服务

- `BEAD_AI_SIMULATION=1` 启用明确标注的本地像素处理模拟。管理员需先发放额度。真实百炼还需配置 `BEAD_AI_PLATFORM_LIVE=1`、`BEAD_AI_ENABLED=1`、密钥和工作空间地址。未知计费任务由管理员核对确认后结算，系统不会自动重试。
- `BEAD_MOCK_PAYMENTS=1` 开启本地模拟订单与付款。默认关闭。模拟商品、库存、订单及会员操作见 [商城演示](commerce-demo.md)。
- `BEAD_DEVELOPMENT_OUTBOX` 指向本机私有目录时，验证码写入该目录的 EML 文件供隔离验收。正式 SMTP 使用 TLS，配置 `BEAD_SMTP_HOST`、`BEAD_SMTP_FROM` 与可选凭据。避免在同一实例同时配置测试收件箱与 SMTP。
- 主动关闭撤销会话、撤回发布，并取消未开始的重绘任务和释放相应额度。已执行或待核账的任务按原规则处理。账号、项目和资产继续保留。

### 已关闭账号的恢复

账号所有者在登录页填写账号并申请恢复。验证码发送到关闭前已验证的邮箱，有效期为 15 分钟。管理员在「平台管理 → 用户」按账号查找，核对支持请求后填写理由和该次验证码。服务在同一事务内消费验证码、恢复登录、撤销旧会话并写入审计。恢复后本人需重新登录，原先撤回的图纸仍按发布流程重新审核。

`BEAD_ACCOUNT_RECOVERY_DAYS` 可设置恢复窗口天数。留空时保留数据且恢复无额外的关闭日期限制。设置后，后台的超期预览只显示截止日期和数量，数据仍保留。未验证邮箱的关闭账号须由项目管理者另行核实身份。正式保留和清理政策待确认。[权限与保留矩阵](platform-access-matrix.md)

具备 SMTP 测试权限后，可先只验证 TLS 握手。应用使用系统信任根和主机名校验。下面的连接检测读取当前进程配置，执行 SMTP NOOP 后断开。

```powershell
& $beadPython -c 'import os, smtplib, ssl; s = smtplib.SMTP_SSL(os.environ["BEAD_SMTP_HOST"], int(os.getenv("BEAD_SMTP_PORT", "465")), context=ssl.create_default_context(), timeout=15); print("SMTP NOOP:", s.noop()[0]); s.quit()'
```

## 备份和恢复

停止源平台的写入后，在 `backend` 目录运行 `python -m platform_api.backup backup <新ZIP> --offline --program <mysqldump路径>`。备份包含 MySQL SQL 和私有图片。该文件需要按私有项目数据保存。

恢复使用不同的空库和新的 `BEAD_ASSET_DIR`，运行 `python -m platform_api.backup restore <ZIP> --offline --program <mysql路径>`。恢复后登录并打开带原图/掩码的项目核查。仅恢复自己创建的可信备份。真实演练及复现见 [测试记录](full-platform-testing.md)。

同一套数据库和资产目录停写后，可运行 `python -m platform_api.asset_maintenance --offline` 查看超过七天的孤立图片或暂存文件数量。确认库和 `BEAD_ASSET_DIR` 匹配后，添加 `--apply` 才会将候选移入该目录下的独立隔离文件夹，并释放未被引用的资产配额。历史版本、重绘任务和成品照片有引用的文件会保留。命令按需手动运行。

## 其他入口

[协作](collaboration.md) · [PWA 与 Chromium 插件](pwa-extension.md) · [Android 调试壳](../mobile/android/README.md) · [任务账本](full-platform-progress.md)
