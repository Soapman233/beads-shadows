# 豆影 · Beads Shadows

将图片或选中的主体转换为拼豆图纸的本地应用。Vue 3 + TypeScript 前端负责图纸生成与编辑，FastAPI 后端负责图片规范化与主体分割。

## 功能

百炼可选重绘接口及配置见[接入说明](docs/bailian.md)，默认关闭；真实AI调用尚待账号配置验证。毕设差距与技术对比见[完善清单](docs/thesis-gap-and-comparison.md)。

- 导入 JPG / PNG，使用整图或框选主体；支持补选、去除和透明预览。
- 对比 32 / 48 / 64 格方案，设置最多 8 / 12 / 16 / 24 / 32 色。
- 平滑取色与主色块取色，原图与图纸并排预览。
- Perler、Hama/Midi、Artkal/S、MARD 参考色卡选择、豆数与用量统计、尺寸估算。
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
./scripts/start.ps1
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

主色块模式可能丢失眼睛、发丝等细节；合并和整色替换也需要人工确认。MARD 数据为屏幕参考，备料请核对实体色号。当前后端使用有界多图存储，仍面向本地单用户使用；不要直接作为公开多用户服务部署。

## 检查

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

目前有 28 项前端逻辑测试，覆盖配色、网格、数量、锁色、项目恢复与整色替换。CI 配置运行前端测试、类型检查、构建及基础CPU后端测试。不包含需要 GPU、个人原图或模型的实验。

## 目录

```text
frontend/    Vue 界面、配色引擎、色卡与本地草稿
backend/     FastAPI 图片处理与主体分割
tests/       无模型依赖的合成数据测试
docs/        架构与验证说明
```

## 开源来源

项目代码采用 [MIT](LICENSE)。新增四品牌屏幕参考的色号/HEX事实来自用户指定的 pixel-beads 公开色号页，读取于2026-11-17：Perler124、Hama/Midi91、Artkal/S225、MARD291（标准221加扩展70）。这些是该站录入数量，不代表厂家全部在售颜色或官方实物校色；特殊材质不能由单一HEX完整模拟。来源未提供开放数据许可，相关数据不适用本项目MIT授权，公开分发须单独核对权利边界。详见 [色卡来源](frontend/src/palettes/PIXEL-SOURCES.md)。

旧版 [maxcleme/beadcolors](https://github.com/maxcleme/beadcolors) 的220色子集、MIT声明及原始CSV继续保留，供旧项目与实验兼容；旧项目不会因切换新色卡自动改色。

参考 [Zippland/perler-beads](https://github.com/Zippland/perler-beads) 的制图与编辑工作流，当前工程独立实现，未引入其 AGPL 源码或色卡。第三方来源和边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

本项目为毕业设计阶段的 MVP。欢迎提交复现步骤、问题报告及改进建议。

## 毕设开发版本
`main` 已合入本轮功能：项目列表与可恢复删除、主体掩码修补、图纸缩放/移动/连续画笔/吸色/高亮、Worker后台生成与取消、材料CSV和分块打印。高级方案含可选交换优化候选；实验不足以更换默认算法。

默认启动与开发代理统一使用8765端口；启动脚本会检查并重建过期页面。新界面无slogan。

- [验收与状态](docs/acceptance.md)
- [实际测试](docs/testing.md)、[配色实验](docs/experiments.md)
- [数据结构](docs/data-model.md)、[接口](docs/api.md)、[算法](docs/algorithms.md)
- [使用手册](docs/user-guide.md)、[部署](docs/deployment.md)
- [论文初稿](thesis/draft.md)、[答辩演示](defense/demo-script.md)

实验复现（仓库根目录，Python已安装基础依赖）：
```powershell
backend/.venv/Scripts/python.exe tests/prepare_experiments.py
frontend/node_modules/.bin/tsx.cmd experiments/run.ts
backend/.venv/Scripts/python.exe tests/render_experiments.py
```
公开样例来源见examples/dataset/SOURCES.md；geometric.png为本项目原创几何图。实验产物生成在忽略目录，私有用户回归也单独忽略。本轮功能已同步到远端 main；论文属于工程初稿，真实用户实验、轻薄本和实体制作待本人完成。

## 本轮可靠性、导出与约束

Windows 首次安装：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install.ps1`；日常：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1`。只为当前进程指定执行策略，不修改系统设置。现有环境可通过 `-PythonPath` 传入，独立端口用 `-Port`。详见[部署说明](docs/deployment.md)。

本地分支 `iteration-reliability-quality` 包含独立项目导入、最新内容复制、事务错误保护、矩形局部换色、可选必选候选色/细节区域、黑白符号打印与一键启动。本轮尚未推送远端，main的上一轮功能不等于已包含这些新增改动。细节见[逐项交付](docs/iteration-p0-p2.md)与[18份公开输入实验](docs/iteration-experiments.md)。区域保护存在退化，默认算法保持 hue4。
