# 数据模型
IndexedDB bead-lab升级到2，保留draft/current原始旧草稿，新增projects和resources。项目包含id、name、createdAt、updatedAt、deleted、thumbnail、project。资源以projectId:source和projectId:mask保存；保存元数据和资源在同一事务提交，不计算内容指纹。
外部JSON仍为schemaVersion2，包含源图、掩码与cells；原v1/v2解析保持兼容。不是必须升级外部版本才能增加内部项目目录。导入先校验格式、解码图像和掩码尺寸后替换。
自动保存捕获项目id与快照，串行写入。切换前清除debounce并保存当前项目；完成反馈校验id与版本。旧草稿以legacy-draft项目复制迁移，原记录保留。删除只设置时间，可恢复。资源当前以每项目覆盖写入保存，避免重复编码但仍会写入字符串；尚未做增量存储。
