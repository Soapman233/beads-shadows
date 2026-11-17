# 数据模型
IndexedDB bead-lab升级到2，保留draft/current原始旧草稿，新增projects和resources。项目包含id、name、createdAt、updatedAt、deleted、thumbnail、project。资源以projectId:source和projectId:mask保存；保存元数据和资源在同一事务提交，不计算内容指纹。
外部JSON仍为schemaVersion2，包含源图、掩码与cells；原v1/v2解析保持兼容。不是必须升级外部版本才能增加内部项目目录。导入先校验格式、解码图像和掩码尺寸后创建新本地项目。
自动保存捕获项目id与快照，串行写入。切换前清除debounce并保存当前项目；完成反馈校验id与版本。旧草稿以legacy-draft项目复制迁移，原记录保留。删除只设置时间，可恢复。资源每项目独立，直接比较跳过不变资源写入；仍有读取比较开销。

## 2026-11-17 更新
项目导入默认新ID，原项目先保存；复制前flush最新内存。保存队列捕获调用时快照并校验反馈版本。活动ID独立记录，重命名/复制不切换活动项目；删除保留可恢复语义。资源缺失会拒绝恢复；迁移在同一IDB事务复制旧draft且保留原draft。资源直接比较跳过不变写入，不计算哈希，项目引用与资源在同一事务。thumbnail缺省时保留，显示等比适配。新可选constraints为required色号列表、源图规范化roi闭区间、weight1–4；旧cells不重算。高级无效输入只停留在UI草稿，不进入持久项目。
