# 部署与运行

## Windows 首次安装

需要 Python 3.10+ 与适配 Vite 6 的 Node.js/npm。项目的实际开发验证环境为 Python 3.12 与 Node 24；其他版本需在目标设备复验。

从仓库根目录运行：

```powershell
.\scripts\install.ps1
# 多个 Python 时可明确选择解释器
.\scripts\install.ps1 -PythonPath 'C:\Python312\python.exe'
```

安装脚本创建 `backend/.venv`，安装 `backend/requirements.txt`、执行 `npm ci` 并构建前端。首次安装需要网络；不会下载 SAM 权重或修改驱动。安装失败会停止并指出阶段，不显示成功。

## 日常启动

```powershell
.\scripts\start.ps1 -Cpu
```

浏览器打开终端实际显示的地址，默认 `http://127.0.0.1:8766`。`-Cpu` 显式使用 GrabCut；不带该参数时由后端检查已有 SAM 源码、权重与设备，缺失时退回 GrabCut。终端健康检查显示实际模式和设备，不能仅凭启动参数声称已经使用 SAM。

日常启动不安装依赖、不下载模型、不重新构建。修改前端后可执行：

```powershell
.\scripts\start.ps1 -Cpu -Build
```

已有环境可复用，无需复制虚拟环境：

```powershell
.\scripts\start.ps1 -PythonPath 'D:\existing-env\Scripts\python.exe' -Port 8778 -Cpu
.\scripts\start.ps1 -PythonPath 'D:\existing-env\Scripts\python.exe' -Port 8778 -CheckOnly
```

`-CheckOnly` 检查后端依赖、Node 可用性、现有前端构建和回环端口，不启动服务、不改环境。已有前端构建时 Node 缺失仅提示；重新构建和首次安装必须有 Node/npm。若同传 `-Build -CheckOnly`，仅检查而不构建。

端口占用直接报错，可更换 `-Port`。脚本不会停止占用者，也不接管已有服务。服务只绑定 `127.0.0.1`。按 Ctrl+C 正常结束脚本时，`finally` 清理本脚本创建的服务进程；强制结束整个终端或操作系统终止不能保证清理，出现占用时先识别进程归属。

日志位置在启动输出中给出，使用独立临时目录；不随仓库提交。启动超过60秒未就绪会退出并清理本脚本进程，可通过日志检查已有 SAM 模型加载异常。脚本不启用 reload 或后台常驻。

## 可选 SAM

仅复用已经准备好的官方源码与权重：

```powershell
$env:SAM2_SOURCE = 'D:\models\sam2'
$env:SAM2_CHECKPOINT = 'D:\models\sam2.1_hiera_tiny.pt'
.\scripts\start.ps1
```

模型和源码不随项目发布。`BEAD_DISABLE_SAM=1` 强制禁用 SAM；`-Cpu` 仅对本次子进程生效并恢复原环境值。资源预算环境变量见 [API 文档](api.md)。

## 手工运行与其他平台

Windows 绕过启动脚本的等价命令（前端已经构建）：

```powershell
backend/.venv/Scripts/python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8766
```

macOS/Linux 使用 `python3 -m venv backend/.venv`、`backend/.venv/bin/python -m pip install -r backend/requirements.txt`，在 frontend 执行 `npm ci`、`npm run build`，然后以 `backend/.venv/bin/python` 运行同样的 uvicorn 命令。此平台流程是说明，尚未在本轮目标机器验证。

前端开发检查：frontend 下 `npm test`、`npm run build`。后端CPU检查：仓库根目录 `python -m unittest discover -s tests -p backend_test.py`。CI不要求 GPU 或 SAM 模型。

## 本轮脚本验证记录

- `-CheckOnly`：复用已有开发环境，在独立8778端口通过；实际 Python 3.12.9、Node 24.14.0，后端依赖与现有 dist 可用。
- 端口占用：在8779建立临时监听后，脚本拒绝启动且没有关闭原监听；检测结束由测试本身释放监听。
- 实际服务启动：尝试独立8778 CPU模式，当前受限运行器对回环请求报套接字访问权限错误，未据此记为健康检查通过；需在正常 PowerShell或允许回环通信的运行环境复验。
- 首次在线安装未重跑，避免为脚本验收重复下载现有依赖；安装路径与异常传播已检查，首次新机器安装仍需目标环境验证。

本机既有8765/8766服务不由这些脚本接管或停止；不同端口属于不同浏览器来源，项目存储不会自动互通。迁移通过下载/导入项目完成，不覆盖既有来源草稿。

## 最终启动复验
主执行者在独立8778端口实际运行start.ps1，显示Ready、GrabCut、CPU，中文信息正常；关闭只释放本脚本进程后同端口可再次启动。PowerShell若禁止脚本，使用README的仅当前进程ExecutionPolicy参数。首次在线安装未重复，正常启动不联网下载依赖或模型。开发服务8767保留供当前交付访问。
