# 豆影 · Beads Shadows

将图片或选中的主体转换为拼豆图纸的本地应用。Vue 3 + TypeScript 前端负责图纸生成与编辑，FastAPI 后端负责图片规范化与主体分割。

## 功能

- 导入 JPG / PNG，使用整图或框选主体；支持补选、去除和透明预览。
- 对比 32 / 48 / 64 格方案，设置最多 8 / 12 / 16 / 24 / 32 色。
- 平滑取色与主色块取色，原图与图纸并排预览。
- MARD 社区参考色卡、豆数与用量统计、尺寸估算。
- 单格编辑、锁色、整色替换、合并少量颜色、撤销与重做。
- 浏览器草稿自动保存；导入/导出项目 JSON，导出带坐标、色号和用量的 PNG。

## 快速开始

需要 Node.js 22 LTS、Python 3.11 或 3.12。以下命令在仓库根目录的 PowerShell 中运行：

```powershell
git clone https://github.com/Soapman233/beads-shadows.git
cd beads-shadows
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
backend/.venv/Scripts/python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8765
```

打开 **http://127.0.0.1:8765/**。首次构建必须在启动服务之前完成。macOS / Linux 将 Python 路径换成 `backend/.venv/bin/python`，将 `npm.cmd` 换成 `npm`。

基础安装使用 OpenCV GrabCut CPU 分割，不需要下载模型或安装 CUDA。轻薄本可先用整图制图和 GrabCut；复杂主体质量及耗时取决于图片和硬件，尚无轻薄本实机基准。

开发时，后端保持运行，另开终端执行 `npm.cmd --prefix frontend run dev`，访问 http://127.0.0.1:5173/。

## 使用

1. 导入图片，选择整图或框选主体；检查预览，必要时补选或去除。
2. 生成并选择图纸方案；“自定义”可固定尺寸比较两种取色。
3. 编辑网格，或展开“替换颜色”调整一个色号的全部格子。应用前可预览。
4. 保存项目用于继续编辑，下载 PNG 用于参考制作。

草稿仅保存于当前浏览器地址，`localhost`、`127.0.0.1` 和不同端口分别存储。重要作品请下载项目 JSON 备份。项目文件包含原图和掩码，分享前请检查内容。

## 可选：SAM 2.1 Tiny

GrabCut 之外，可自行安装 [Meta SAM 2](https://github.com/facebookresearch/sam2) 及其要求的 PyTorch / TorchVision。按官方平台说明安装依赖，将官方源码置于 `backend/vendor/sam2-main`，或安装可导入的 `sam2` 包。

从[官方地址](https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt)下载 Tiny 权重，放入 `backend/models/sam2.1_hiera_tiny.pt`，也可用环境变量 `SAM2_CHECKPOINT` 指定路径。配置使用 `configs/sam2.1/sam2.1_hiera_t.yaml`。重启后在“项目信息”查看实际运行模式；加载失败时回退 GrabCut。仓库不分发 SAM 源码、权重或 CUDA 环境。

## 原理与限制

前景掩码确定有效格子；每格取平均色，或从 RGB 分桶中提取主色。随后在离散参考色卡中选色，以 Oklab 明度、色度、色相分解的加权距离匹配，当前色相权重为 4。这是产品启发式，不是标准 Delta E，也不保证全局最优或实体零色差。参见 [架构说明](docs/architecture.md)。

主色块模式可能丢失眼睛、发丝等细节；合并和整色替换也需要人工确认。MARD 数据为屏幕参考，备料请核对实体色号。当前后端仅保留一张活动图片，适合本地单用户使用；不要直接作为公开多用户服务部署。

## 检查

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

目前有 17 项前端逻辑测试，覆盖配色、网格、数量、锁色、项目恢复与整色替换。CI 运行测试、类型检查、构建及后端语法检查。不包含需要 GPU、个人原图或模型的实验。

## 目录

```text
frontend/    Vue 界面、配色引擎、色卡与本地草稿
backend/     FastAPI 图片处理与主体分割
tests/       无模型依赖的合成数据测试
docs/        架构与验证说明
```

## 开源来源

项目代码采用 [MIT](LICENSE)。色卡数据来自 [maxcleme/beadcolors](https://github.com/maxcleme/beadcolors)，其 MIT 声明及原始 CSV 保存在 `frontend/src/palettes/`。当前使用经典 A–H、M 体系的 220 色子集，不等同于上游全部 MARD 数据；H1 暂未纳入，源数据没有材质或透明度字段。

参考 [Zippland/perler-beads](https://github.com/Zippland/perler-beads) 的制图与编辑工作流，当前工程独立实现，未引入其 AGPL 源码或色卡。第三方来源和边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

本项目为毕业设计阶段的 MVP。欢迎提交复现步骤、问题报告及改进建议。
