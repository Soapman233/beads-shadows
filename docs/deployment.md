# 部署与运行
按README安装基础依赖并构建前端，在仓库根目录运行：
```
backend/.venv/Scripts/python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8766
```
当前开发验证复用旧mvp/backend/.venv中的Python，未把虚拟环境复制到仓库。原8765服务保留。生产仅绑定回环地址。
BEAD_DISABLE_SAM=1明确使用CPU。可选SAM2_SOURCE指定已有官方源码，SAM2_CHECKPOINT指定已有权重；无模型自动GrabCut。依赖和权重不随源码发布。资源预算环境变量见api.md。
前端npm ci、npm test、npm run build。后端python -m unittest discover -s tests -p backend_test.py。CI使用基础CPU依赖，不要求GPU或模型。
