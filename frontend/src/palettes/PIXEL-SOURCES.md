# pixel-beads 页面色号事实来源

读取日期：2026-11-17。仅记录公开页面的色号与HEX数字事实；没有复制站点代码、描述文案、颜色名称、图片或商标图形。来源网站未提供开放数据许可证，这些记录不适用本项目MIT授权声明，也不声称厂家认证或授权。后续公开分发前须单独核对数据权利边界。

|目录id|页面宣称录入数量|当前实际提取|来源|
|---|---:|---:|---|
|pixel-perler|124|124|https://www.pixel-beads.com/zh/perler-bead-color-chart|
|pixel-hama-midi|91|91|https://www.pixel-beads.com/zh/hama-bead-color-chart|
|pixel-artkal-s|225|225|https://www.pixel-beads.com/zh/artkal-bead-color-chart|
|pixel-mard|291|291|https://www.pixel-beads.com/zh/mard-bead-color-chart|

前三页的网页文本解析只包含色号，未暴露HEX。直接HTTP读取Perler页收到Cloudflare managed challenge（Just a moment / Enable JavaScript and cookies）；随后通过正常浏览器读取公开页面可见色块的色号与style HEX，未绕过挑战或调用内部接口。三份事实数据分别含124/91/225个唯一色号，已核验HEX格式。没有用其他来源或猜测RGB补齐。

MARD的数字事实来自页面可见文本：A26、B32、C29、D26、E24、F25、G21、H23、M15、P23、Q5、R28、T1、Y5、ZG8，共291项。A–H及M共221，扩展70。ZG1–ZG8记录的是页面右侧显色HEX，不代表未照射时的透明外观；珠光、透明、变色等特殊材质无法用单一HEX模拟。目录为参考色表，非物理校色模型。

`pixel-perler.ts`、`pixel-hama.ts`、`pixel-artkal.ts`、`pixel-mard.ts`是本项目独立编写的数据包装，仅包含code/hex字段。目录版本记录读取日期；不计算数据哈希。旧`mard.ts`及其MIT来源保留，旧项目原palette/cells不自动重算或重映射。

同一色号仅在所属品牌/系列内有意义；Hama的H系列与MARD的H系列不能按编号混用。目录使用稳定id区分来源；旧图纸必须保留其原始HEX、色表与cells。页面录入数量不是厂家当前全部在售色数，特殊材质参考也不等同实物颜色测量。
