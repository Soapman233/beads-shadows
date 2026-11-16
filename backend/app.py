"""Local, single-work-image segmentation service."""
from __future__ import annotations
import base64
import io
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
ROOT = Path(__file__).resolve().parent
lock = threading.Lock()
current: dict = {}
predictor = None
torch = None
mode = 'GrabCut'
device = 'CPU'
detail = '传统分割降级模式；SAM 2.1 未就绪。'

def initialize_model():
    global predictor, torch, mode, device, detail
    checkpoint = Path(os.environ.get('SAM2_CHECKPOINT', str(ROOT / 'models/sam2.1_hiera_tiny.pt')))
    if not checkpoint.exists():
        detail = '传统分割降级模式；未找到 SAM 2.1 Tiny 权重。'
        return
    try:
        source = ROOT / 'vendor/sam2-main'
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
@app.middleware('http')
async def production_api_prefix(request, call_next):
    # Same-origin production UI uses /api; Vite strips this prefix in dev.
    if request.scope['path'].startswith('/api/'):
        request.scope['path'] = request.scope['path'][4:]
    return await call_next(request)

app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_methods=['GET','POST'], allow_headers=['Content-Type'])

@app.exception_handler(RequestValidationError)
async def invalid_request(_request, _error):
    return JSONResponse(status_code=400, content={'detail':'请求字段无效，请检查图片、框选坐标和修正点'})

def png_url(image: Image.Image):
    output = io.BytesIO()
    image.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')

@app.get('/health')
def health():
    return {'ready': True, 'mode': mode, 'device': device, 'detail': detail}

@app.post('/images')
async def upload(file: UploadFile = File(...)):
    contents = await file.read(MAX_BYTES + 1)
    if len(contents) > MAX_BYTES:
        raise HTTPException(413, '图片不得超过20MB')
    try:
        with Image.open(io.BytesIO(contents)) as source:
            if source.format not in ('JPEG', 'PNG'):
                raise HTTPException(400, '仅支持JPG和PNG图片')
            if source.width * source.height > MAX_PIXELS:
                raise HTTPException(413, '解码后图片不得超过2000万像素')
            oriented = ImageOps.exif_transpose(source)
            rgba = oriented.convert('RGBA')
            rgba.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
            alpha = np.asarray(rgba)[:, :, 3].copy()
            rgb_image = Image.new('RGB', rgba.size, 'white')
            rgb_image.paste(rgba, mask=rgba.getchannel('A'))
            rgb = np.array(rgb_image)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, '图片无法解码或尺寸过大') from exc
    image_id = uuid.uuid4().hex
    # Same lock protects predictor state, image identity and updates.
    with lock:
        current.clear()
        current.update(id=image_id, rgb=rgb, alpha=alpha, encoded=False)
    return {'imageId': image_id, 'width': rgb.shape[1], 'height': rgb.shape[0], 'image': png_url(rgba)}

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
def segment(request: SegmentRequest):
    with lock:
        if current.get('id') != request.imageId:
            raise HTTPException(409, '图片已更换，请使用当前图片重新分割')
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
                    if not current['encoded']:
                        if device=='cuda': torch.cuda.synchronize()
                        started=time.perf_counter()
                        predictor.set_image(rgb)
                        if device=='cuda': torch.cuda.synchronize()
                        encode_ms=(time.perf_counter()-started)*1000
                        current['encoded']=True
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
            raise HTTPException(503,f'分割失败：{type(exc).__name__}: {exc}') from exc
        return {'imageId':request.imageId,'revision':request.revision,'mask':png_url(Image.fromarray(result)),'mode':mode,'device':device,'timings':{'encodeMs':round(encode_ms,2),'segmentMs':round(segment_ms,2)}}

dist=ROOT.parent/'frontend/dist'
if dist.exists():
    app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
