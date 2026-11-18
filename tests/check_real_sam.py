"""Opt-in actual SAM lifecycle check. Existing local model only; never downloads.

Run with SAM2_CHECKPOINT/SAM2_SOURCE pointing to already installed resources.
This is separate from the small default CPU unit suite.
"""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import sys
import time

os.environ.pop('BEAD_DISABLE_SAM', None)
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ.setdefault('OMP_NUM_THREADS', '4')
os.environ.setdefault('MKL_NUM_THREADS', '4')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import numpy as np
from PIL import Image
import torch
from unittest.mock import patch

# Force the production model's normal CPU-loading branch for this opt-in check.
# Only device selection is overridden; predictor/model weights remain real.
torch.set_num_threads(4)
with patch.object(torch.cuda, 'is_available', return_value=False):
    import app

out = ROOT / 'experiments/private/real-sam-lifecycle.json'
out.parent.mkdir(exist_ok=True, parents=True)
result = {'actualModel': app.predictor is not None, 'mode': app.mode,
          'device': app.device, 'detail': app.detail, 'runs': []}

class Upload:
    def __init__(self, data): self.data = data
    async def read(self, limit): return self.data[:limit]

async def upload(name):
    with Image.open(ROOT / 'examples/dataset' / name) as image:
        image = image.convert('RGB')
        image.thumbnail((256, 256))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
    return await app.upload(Upload(buffer.getvalue()))

try:
    if app.predictor is None:
        raise RuntimeError('Existing SAM failed to initialize; see detail')
    app.torch.set_num_threads(4)
    images = [asyncio.run(upload('pet.png')), asyncio.run(upload('object.png'))]
    masks = []
    # A→A→B→A confirms both cache reuse and re-encoding after another image.
    for revision, which in enumerate([0, 0, 1, 0], 1):
        image = images[which]
        w, h = image['width'], image['height']
        request = app.SegmentRequest(imageId=image['imageId'], revision=revision,
            box=(w*.08, h*.08, w*.92, h*.92),
            points=[app.Point(x=w*.5, y=h*.5, label=1)])
        start = time.perf_counter()
        response = app.segment(request)
        decoded = np.asarray(Image.open(io.BytesIO(base64.b64decode(response['mask'].split(',')[1]))))
        assert decoded.shape == (h, w)
        assert np.any(decoded)
        assert response['imageId'] == request.imageId
        assert response['revision'] == revision
        assert app.encoded_image_id == request.imageId
        assert response['mode'] == 'SAM 2.1 Tiny'
        masks.append(decoded)
        result['runs'].append({'image': 'A' if which == 0 else 'B',
            'revision': revision, 'foregroundPixels': int(np.count_nonzero(decoded)),
            'width': w, 'height': h, 'timings': response['timings'],
            'totalMs': round((time.perf_counter()-start)*1000, 2)})
    assert result['runs'][1]['timings']['encodeMs'] == 0
    assert result['runs'][0]['timings']['encodeMs'] > 0
    assert result['runs'][2]['timings']['encodeMs'] > 0
    assert result['runs'][3]['timings']['encodeMs'] > 0
    # Direct mask array assertions, not fingerprints or hashes.
    assert np.array_equal(masks[0], masks[1])
    assert np.array_equal(masks[0], masks[3])
    result.update({'passed': True, 'cachedAEqual': True, 'finalAEqual': True,
                   'scope': f'real {app.device} model via formal backend functions; not HTTP transport or UI'})
except Exception as error:
    result.update({'passed': False, 'error': str(error)})
    raise
finally:
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
