# 本地图像 API

## 多用户接口

配置 MySQL 后可使用 /docs 查看当前请求字段。业务接口按 /api 前缀同源调用。账号写操作使用 X-CSRF-Token，会话界面使用 X-Bead-Account 核对身份。私有资源通过所属账号或明确协作关系授权。

接口分组为 auth、account、assets、projects、palettes、inventory、builds、publications、notifications、ai、collab、shop、admin。[验收索引](full-platform-acceptance.md)

## 本地兼容模式

服务仅供本地单用户使用。默认监听回环地址；开发服务器代理 `/api` 到后端，生产服务同时接受下述裸路径与 `/api` 前缀。默认端口可由启动命令指定，不绑定用户当前活动的旧工程端口进行测试。

## 健康检查

`GET /health`

返回 `ready`、`mode`、`device`、`detail`，以及 `normalizationVersion` 和 `imageStore` 配置。`ready:true` 表示基础服务可用；SAM缺失时仍可使用GrabCut，不等于SAM就绪。`imageStore` 包含 `maxImages`、`maxBytes`、`idleTtlSeconds`。

## 注册图像

`POST /images`，multipart字段 `file`，接受JPG/PNG。

限制：上传20MiB、解码20,000,000像素，工作图长边不超过1536。超限返回413；无效图片返回400。处理EXIF方向、ICC到sRGB、alpha和预乘缩放，返回：

```json
{
  "imageId": "随机标识",
  "width": 640,
  "height": 480,
  "image": "data:image/png;base64,...",
  "normalization": {
    "version": "srgb-premultiplied-v1",
    "colorProfile": "assumed-srgb",
    "alphaResize": "premultiplied"
  }
}
```

`colorProfile` 为 `converted-to-srgb`、`assumed-srgb` 或 `invalid-icc-assumed-srgb`。最后一项表示ICC无效，回退RGB转换并按sRGB解释；不能据此声称原图颜色被准确恢复。工作PNG为制图原色，分割模型另用白背景合成RGB；二者不混用。

`imageId`是当前进程的临时身份，不写成项目永久资源身份。恢复本地项目后，需要继续分割时重新上传保存的工作图。

## 分割

`POST /segment`，JSON：

```json
{
  "imageId": "注册返回的标识",
  "box": [10, 20, 300, 400],
  "points": [{"x": 80, "y": 90, "label": 1}],
  "revision": 3
}
```

坐标基于返回的工作图，以左上角为原点。`box`为XYXY，右/下边界不含；至少2×2像素。点坐标必须在图内，`label`为1保留或0去除，最多200点。`revision`为非负整数，服务回传它；客户端须自行拒绝旧版本结果。

响应字段：`imageId`、`revision`、`mask`、`mode`、`device`、`timings`。mask为同工作图尺寸的灰度PNG数据URL，0背景、255前景。原图alpha低于128的位置强制背景。timings含 `encodeMs` 和 `segmentMs`，单位毫秒；CUDA计时包含必要同步。不是完整端到端等待时间，也不是冷启动耗时。

GrabCut将点扩展为小圆标注，XYXY转换为OpenCV所需矩形语义。SAM只持有一张图的特征：同图复用，A→B→A切换时重新编码A。图像ID与编码ID分开跟踪，所有模型访问串行。

## 生命周期与内存

图像注册表按ID管理，默认最多8张、数组估算64MiB、空闲30分钟过期。LRU基于访问时间/次序；上传或取图时惰性清理，不设后台扫描线程。当前推理图被pin，不能被TTL/LRU回收。空闲时间从推理完成后重新计。

预算为保存的RGB/alpha NumPy数组字节数，不含Python对象、HTTP响应编码临时内存、模型和显存。超出预算的单图拒绝；新图可以回收最久未使用图。最近128次回收原因作为有界记录保存，更久以前的ID可能只返回未找到。

环境变量：

| 变量 | 默认 | 用途 |
| --- | --- | --- |
| BEAD_MAX_IMAGES | 8 | 注册图像数上限 |
| BEAD_IMAGE_MEMORY_MB | 64 | RGB/alpha数组预算MiB |
| BEAD_IMAGE_TTL_SECONDS | 1800 | 空闲有效期 |
| BEAD_DISABLE_SAM | 未设置 | 设1时显式使用CPU GrabCut |
| SAM2_CHECKPOINT | backend/models/sam2.1_hiera_tiny.pt | 已有模型路径 |
| SAM2_SOURCE | backend/vendor/sam2-main | 已有官方源码路径 |

可用环境变量复用旧工程的模型与源码，无需复制模型或环境进仓库。

## 错误

多数错误保持 `{detail:中文字符串}`：400输入无效/空分割，413容量超限，503推理失败。图像生命周期错误增加机器可读 `code`：

| HTTP | code | 含义 |
| --- | --- | --- |
| 404 | IMAGE_NOT_FOUND | 当前进程没有该ID |
| 410 | IMAGE_EXPIRED | 空闲到期 |
| 410 | IMAGE_EVICTED | 因数量/内存预算回收 |

客户端可从项目源图重新注册并重试一次；不能在持续失败时无限重试。切换项目/图片时必须使旧请求失效，不将晚到结果覆盖新图。

本文件描述实现契约，运行结果与替身/真实模型边界见testing及验收记录，不以接口存在代表质量通过。
