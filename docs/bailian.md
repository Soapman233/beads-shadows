# 百炼像素画重绘接入

实现日期：2026-11-18。默认关闭，未执行真实付费调用，尚未验证模型效果、账号权限与生产返回域名。

## 配置

在启动后端的同一个PowerShell窗口设置环境变量（不要提交真实密钥）：

```powershell
$env:BEAD_AI_ENABLED = '1'
$env:DASHSCOPE_API_KEY = '<本机填入密钥>'
$env:BEAD_BAILIAN_ENDPOINT = 'https://<工作空间ID>.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'
./scripts/start.ps1
```

`.env.example`仅是说明模板，脚本不会自动加载.env。服务地域与密钥必须一致；支持北京或新加坡工作空间官方域名。默认模型固定为`qwen-image-edit-plus`。停用时设置BEAD_AI_ENABLED=0并重启后端。使用复用环境时向start.ps1传-PythonPath。

## 工作流与接口

导入原图，在“照片 → 像素画 → 图纸”展开面板。未配置时仍能导入外部像素画；配置后出现上传及费用确认与AI重绘按钮。结果先预览，采用时创建新项目，原项目保留。透明区域不计豆；不透明白色仍为白豆，生成模型未提供真实透明背景时需在主体选择中修补。

- GET /api/ai/capabilities：available/provider/model/message。不返回密钥或配置端点。
- POST /api/ai/pixel-art：JSON image（PNG/JPG data URL）、prompt（1–1000字符）、consent=true。
- 成功返回规范化PNG data URL、provider/model；失败返回标准detail。关闭或缺配置503、未确认400、进程内已有请求429、上游失败502。
- 后端单次只生成1张，无自动重试，限制输入和输出体积、像素量、单次网络超时，服务端保存密钥。不接受浏览器传任意端点；下载只允许官方OSS域名且拒绝重定向。

若百炼调整输出域名，需要核对官方响应后更新允许域名，不能直接放开任意URL。关闭页面只中止客户端等待，不保证上游取消或退款。请求超时/下载失败可能已计费，先查控制台再重试。

## 验证与后续

tests/ai_images_test.py的3项测试覆盖默认关闭/未同意不联网、单图请求与模拟响应、拒绝非供应商输出地址。真实调用未验证。账号就绪后先1张测试，确认费用和地域，再做人像/宠物/双人小样本评估；AI图像质量与传统色卡映射应分开评估。

官方协议参考：[Qwen图像编辑API](https://help.aliyun.com/en/model-studio/qwen-image-edit-api)。上线公网前还需用户认证、按用户限流、持久任务状态与预算配额；当前只面向本机单用户，进程锁不是分布式任务队列。
