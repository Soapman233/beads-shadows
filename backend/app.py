"""Local segmentation service with bounded image lifetime and shared SAM predictor."""
from __future__ import annotations
import asyncio
import base64
import io
import json
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from image_store import ImageStore, ImageUnavailable
from normalization import normalize_image, NORMALIZATION_VERSION
from pydantic import BaseModel, Field
from ai_images import router as ai_router
from platform_api.auth import User, optional_user, router as auth_router
from platform_api.db import enabled as platform_enabled
from platform_api.projects import router as projects_router
from platform_api.catalog import router as catalog_router
from platform_api.inventory import router as inventory_router
from platform_api.builds import router as builds_router
from platform_api.publications import router as publications_router
from platform_api.ai_jobs import router as jobs_router, run_one as run_ai_job
from platform_api.extensions import router as extensions_router
from platform_api.social import router as social_router
from platform_api.notifications import router as notifications_router
from platform_api.commerce import router as commerce_router
from platform_api.account_tools import router as account_router
from platform_api.collab import router as collab_router, watch_room

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
ROOT = Path(__file__).resolve().parent
APP_ID = 'beads-shadows'
BACKEND_VERSION = '2026.11.17.1'
FRONTEND_DIST = ROOT.parent / 'frontend' / 'dist'
lock = threading.Lock()
encoded_image_id = None

def invalidate_encoding(image_id):
    global encoded_image_id
    if encoded_image_id == image_id:
        encoded_image_id = None

store = ImageStore(
    max_images=int(os.environ.get('BEAD_MAX_IMAGES', '8')),
    max_bytes=int(float(os.environ.get('BEAD_IMAGE_MEMORY_MB', '64')) * 1024 * 1024),
    ttl_seconds=float(os.environ.get('BEAD_IMAGE_TTL_SECONDS', '1800')),
    on_remove=invalidate_encoding,
)
predictor = None
torch = None
mode = 'GrabCut'
device = 'CPU'
detail = '传统分割降级模式；SAM 2.1 未就绪。'

def initialize_model():
    global predictor, torch, mode, device, detail
    if os.environ.get('BEAD_DISABLE_SAM') == '1':
        detail = '传统分割模式；本进程显式禁用 SAM。'
        return
    checkpoint = Path(os.environ.get('SAM2_CHECKPOINT', str(ROOT / 'models/sam2.1_hiera_tiny.pt')))
    if not checkpoint.exists():
        detail = '传统分割降级模式；未找到 SAM 2.1 Tiny 权重。'
        return
    try:
        source = Path(os.environ.get('SAM2_SOURCE', str(ROOT / 'vendor/sam2-main')))
        if source.exists():
            sys.path.insert(0, str(source))
        import torch as pt
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        torch = pt
        device = 'cuda' if pt.cuda.is_available() else 'cpu'
        predictor = SAM2ImagePredictor(build_sam2('configs/sam2.1/sam2.1_hiera_t.yaml', str(checkpoint), device=device, apply_postprocessing=False))
        mode = 'SAM 2.1 Tiny'
        detail = '预训练单图分割；CUDA 扩展后处理关闭。'
    except Exception as exc:
        predictor = None
        device = 'CPU'
        detail = f'传统分割降级模式；SAM 加载失败：{type(exc).__name__}: {exc}'

initialize_model()
app = FastAPI(title='拼豆 MVP 分割服务')
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(catalog_router)
app.include_router(inventory_router)
app.include_router(builds_router)
app.include_router(publications_router)
app.include_router(extensions_router)
app.include_router(social_router)
app.include_router(notifications_router)
app.include_router(commerce_router)
app.include_router(account_router)
app.include_router(collab_router)
app.add_api_websocket_route('/api/collab/ws/{room_id}', watch_room)
if not platform_enabled():
    app.include_router(ai_router)
else:
    app.include_router(jobs_router)

    async def job_loop():
        while True:
            try:
                await asyncio.to_thread(run_ai_job)
            except Exception as exc:
                # Error details may hold provider response data. Log only the exception class.
                print('AI task loop:', type(exc).__name__, file=sys.stderr)
                await asyncio.sleep(8)
            await asyncio.sleep(1)

    @app.on_event('startup')
    async def start_job_loop():
        app.state.job_loop = asyncio.create_task(job_loop())

    @app.on_event('shutdown')
    async def stop_job_loop():
        app.state.job_loop.cancel()
@app.middleware('http')
async def production_api_prefix(request, call_next):
    # Same-origin production UI uses /api; Vite strips this prefix in dev.
    public_path = request.scope['path']
    if request.scope['path'].startswith('/api/'):
        request.scope['path'] = request.scope['path'][4:]
    response = await call_next(request)
    if public_path.startswith('/api/') or public_path in ('/', '/index.html', '/build-info.json', '/health') or public_path.endswith('.html'):
        response.headers['Cache-Control'] = 'no-store'
    return response

app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_methods=['GET','POST'], allow_headers=['Content-Type'])

@app.exception_handler(RequestValidationError)
async def invalid_request(_request, _error):
    return JSONResponse(status_code=400, content={'detail':'请求字段无效，请检查图片、框选坐标和修正点'})

@app.exception_handler(ImageUnavailable)
async def unavailable_image(_request, error):
    messages = {
        'IMAGE_EXPIRED': '图片因长时间未使用已过期，请重新注册项目源图',
        'IMAGE_EVICTED': '图片已被存储预算回收，请重新注册项目源图',
        'IMAGE_NOT_FOUND': '没有找到图片，请重新注册项目源图',
    }
    return JSONResponse(status_code=404 if error.code == 'IMAGE_NOT_FOUND' else 410,
                        content={'code': error.code, 'detail': messages[error.code]})

def png_url(image: Image.Image):
    output = io.BytesIO()
    image.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')

def frontend_build_info():
    try:
        info = json.loads((FRONTEND_DIST / 'build-info.json').read_text(encoding='utf-8'))
        if info.get('appId') == APP_ID and all(isinstance(info.get(key), str) for key in ('buildId', 'builtAt')):
            return {key: info[key] for key in ('appId', 'buildId', 'builtAt')}
    except (OSError, ValueError, AttributeError):
        pass
    return None

@app.get('/health')
def health():
    return {'appId': APP_ID, 'backendVersion': BACKEND_VERSION,
            'frontendAvailable': (FRONTEND_DIST / 'index.html').is_file(),
            'frontendBuild': frontend_build_info(), 'ready': True, 'mode': mode, 'device': device, 'detail': detail, 'platformEnabled': platform_enabled(), 'normalizationVersion': NORMALIZATION_VERSION, 'imageStore': {'maxImages':store.max_images,'maxBytes':store.max_bytes,'idleTtlSeconds':store.ttl_seconds}}

def image_scope(request: Request, response: Response, user: User | None = Depends(optional_user)):
    if not platform_enabled():
        return None
    if user is not None:
        return 'user', user.id
    guest = request.cookies.get('bead_guest', '')
    if len(guest) != 43 or not guest.isascii() or not guest.replace('-', 'a').replace('_', 'a').isalnum():
        guest = secrets.token_urlsafe(32)
        response.set_cookie('bead_guest', guest, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https')
    return 'guest', guest

def cache_key(scope, image_id):
    return (scope, image_id) if scope is not None else image_id

@app.post('/images')
async def upload_route(file: UploadFile = File(...), scope=Depends(image_scope)):
    return await upload(file, scope)

async def upload(file: UploadFile, scope=None):
    contents = await file.read(MAX_BYTES + 1)
    if len(contents) > MAX_BYTES:
        raise HTTPException(413, '图片不得超过20MB')
    try:
        with Image.open(io.BytesIO(contents)) as source:
            if source.format not in ('JPEG', 'PNG'):
                raise HTTPException(400, '仅支持JPG和PNG图片')
            if source.width * source.height > MAX_PIXELS:
                raise HTTPException(413, '解码后图片不得超过2000万像素')
            rgba, rgb, alpha, normalization = normalize_image(source)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, '图片无法解码或尺寸过大') from exc
    image_id = uuid.uuid4().hex
    # Same lock protects predictor state, image identity and updates.
    with lock:
        try:
            store.put(cache_key(scope, image_id), rgb, alpha, normalization)
        except ValueError as exc:
            raise HTTPException(413, '图片超出当前图像存储预算，请使用较小图片或提高存储配置') from exc
    return {'imageId': image_id, 'width': rgb.shape[1], 'height': rgb.shape[0], 'image': png_url(rgba), 'normalization':normalization}

class Point(BaseModel):
    x: float
    y: float
    label: int = Field(ge=0, le=1)

class SegmentRequest(BaseModel):
    imageId: str
    box: tuple[float, float, float, float]
    points: list[Point] = Field(default_factory=list, max_length=200)
    revision: int = Field(ge=0)

@app.post('/segment')
def segment_route(request: SegmentRequest, scope=Depends(image_scope)):
    return segment(request, scope)

def segment(request: SegmentRequest, scope=None):
    global encoded_image_id
    key = cache_key(scope, request.imageId)
    with lock, store.using(key) as current:
        rgb = current['rgb']
        h, w = rgb.shape[:2]
        box = np.array(request.box, dtype=float)
        if not np.isfinite(box).all():
            raise HTTPException(400, '框坐标必须为有限数值')
        x0,y0,x1,y1 = np.round(box).astype(int)
        if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h) or (x1-x0)<2 or (y1-y0)<2:
            raise HTTPException(400, '框选范围无效，至少需要2×2像素')
        for p in request.points:
            if not np.isfinite([p.x,p.y]).all() or not (0<=p.x<w and 0<=p.y<h):
                raise HTTPException(400, '修正点超出图片范围')
        encode_ms = 0.0
        try:
            if predictor is not None:
                with torch.inference_mode():
                    if encoded_image_id != key:
                        if device=='cuda': torch.cuda.synchronize()
                        started=time.perf_counter()
                        encoded_image_id = None
                        predictor.set_image(rgb)
                        if device=='cuda': torch.cuda.synchronize()
                        encode_ms=(time.perf_counter()-started)*1000
                        encoded_image_id=key
                    if device=='cuda': torch.cuda.synchronize()
                    started=time.perf_counter()
                    coords=np.array([[p.x,p.y] for p in request.points],dtype=np.float32) if request.points else None
                    labels=np.array([p.label for p in request.points],dtype=np.int32) if request.points else None
                    masks,_,_=predictor.predict(point_coords=coords,point_labels=labels,box=np.array([x0,y0,x1,y1],dtype=np.float32),multimask_output=False)
                    if device=='cuda': torch.cuda.synchronize()
                    result=masks[0].astype(np.uint8)*255
                    segment_ms=(time.perf_counter()-started)*1000
            else:
                started=time.perf_counter()
                labels=np.full((h,w),cv2.GC_BGD,dtype=np.uint8)
                labels[y0:y1,x0:x1]=cv2.GC_PR_FGD
                # Ensure background samples even for a whole-image frame.
                labels[[0,-1],:]=cv2.GC_BGD
                labels[:,[0,-1]]=cv2.GC_BGD
                radius=max(2,round(min(w,h)*0.012))
                for p in request.points:
                    cv2.circle(labels,(round(p.x),round(p.y)),radius,cv2.GC_FGD if p.label else cv2.GC_BGD,-1)
                if not np.any(labels==cv2.GC_BGD) or not np.any((labels==cv2.GC_FGD)|(labels==cv2.GC_PR_FGD)):
                    raise HTTPException(400,'请保留有效的前景和背景标记')
                cv2.grabCut(cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR),labels,(x0,y0,x1-x0,y1-y0),np.zeros((1,65)),np.zeros((1,65)),5,cv2.GC_INIT_WITH_MASK)
                result=np.where((labels==cv2.GC_FGD)|(labels==cv2.GC_PR_FGD),255,0).astype(np.uint8)
                segment_ms=(time.perf_counter()-started)*1000
            result[current['alpha']<128]=0
            if not np.any(result):
                raise HTTPException(400,'未提取到前景，请扩大框选或添加保留点')
        except HTTPException:
            raise
        except Exception as exc:
            encoded_image_id = None
            raise HTTPException(503,f'分割失败：{type(exc).__name__}: {exc}') from exc
        return {'imageId':request.imageId,'revision':request.revision,'mask':png_url(Image.fromarray(result)),'mode':mode,'device':device,'timings':{'encodeMs':round(encode_ms,2),'segmentMs':round(segment_ms,2)}}

dist=FRONTEND_DIST
if dist.exists():
    app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')

