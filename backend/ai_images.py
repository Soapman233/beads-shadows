"""Optional Bailian adapter. Disabled by default; no retries or secret logging."""
import base64
import io
import json
import os
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from PIL import Image
from normalization import normalize_image

router = APIRouter(prefix='/ai')
gate = threading.Lock()
LIMIT = 10 * 1024 * 1024
MODEL = 'qwen-image-edit-plus'
SUFFIX = '/api/v1/services/aigc/multimodal-generation/generation'

def settings():
    endpoint = os.getenv('BEAD_BAILIAN_ENDPOINT', '').strip()
    host = urlsplit(endpoint).hostname or ''
    valid = (urlsplit(endpoint).scheme == 'https' and
             re.fullmatch(r'[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com', host) is not None and
             endpoint == 'https://' + host + SUFFIX)
    key = os.getenv('DASHSCOPE_API_KEY', '').strip()
    enabled = os.getenv('BEAD_AI_ENABLED') == '1'
    return enabled and valid and bool(key), endpoint, key

@router.get('/capabilities')
def capabilities():
    ready, _, _ = settings()
    return {'available': ready, 'provider': '百炼', 'model': MODEL,
            'message': '照片会上传至百炼，可能产生费用' if ready else '未启用百炼；可先导入外部像素画'}

class EditRequest(BaseModel):
    image: str = Field(max_length=14_000_000)
    prompt: str = Field(min_length=1, max_length=1000)
    consent: bool = False

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('redirect refused')

def read_remote(request, limit):
    with urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('response too large')
    return data

def payload(image, prompt):
    return {'model': MODEL, 'input': {'messages': [{'role': 'user', 'content': [{'image': image}, {'text': prompt}]}]},
            'parameters': {'n': 1, 'prompt_extend': False, 'watermark': False}}

def result_url(body):
    content = body['output']['choices'][0]['message']['content']
    url = next(item['image'] for item in content if 'image' in item)
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or not re.fullmatch(r'[a-zA-Z0-9-]+\.oss-[a-zA-Z0-9-]+\.aliyuncs\.com', parsed.hostname or ''):
        raise ValueError('unexpected output host')
    return url

@router.post('/pixel-art')
def edit(request: EditRequest):
    ready, endpoint, key = settings()
    if not ready:
        raise HTTPException(503, '百炼未配置，请查看 docs/bailian.md')
    if not request.consent:
        raise HTTPException(400, '请先确认上传照片至百炼及可能的费用')
    try:
        prefix, encoded = request.image.split(',', 1)
        if prefix not in ('data:image/png;base64', 'data:image/jpeg;base64'):
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > LIMIT:
            raise ValueError()
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 20_000_000: raise ValueError()
            image.verify()
    except Exception as exc:
        raise HTTPException(400, '参考图须为10MB以内的有效PNG或JPG') from exc
    if not gate.acquire(blocking=False):
        raise HTTPException(429, '已有AI请求处理中，请稍后再试')
    try:
        req = urllib.request.Request(endpoint, data=json.dumps(payload(request.image, request.prompt)).encode(),
              headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
        body = json.loads(read_remote(req, 2 * 1024 * 1024))
        raw = read_remote(urllib.request.Request(result_url(body)), 20 * 1024 * 1024)
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 20_000_000: raise ValueError()
            rgba, _, _, _ = normalize_image(image)
        output = io.BytesIO(); rgba.save(output, format='PNG')
        return {'image': 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode(), 'provider': 'bailian', 'model': MODEL}
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f'百炼请求失败（HTTP {exc.code}），请检查地域、额度和模型权限；未自动重试') from exc
    except Exception as exc:
        raise HTTPException(502, 'AI请求超时或结果无法读取；服务端可能已计费，请先检查控制台，勿连续重试') from exc
    finally:
        gate.release()
