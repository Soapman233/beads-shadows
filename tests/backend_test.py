"""Small CPU P0 checks. Run using unittest discovery or this file directly.
SAM lifecycle uses a controlled fake; the separate GrabCut check runs OpenCV.
No user images, model download or content hashes.
"""
import asyncio
import base64
from contextlib import nullcontext
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageCms

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
sys.path.insert(0, str(BACKEND))
from image_store import ImageStore, ImageUnavailable
from normalization import normalize_image


class StoreAndNormalizationTest(unittest.TestCase):
    def test_registry_lru_budget_ttl_and_active_protection(self):
        now = [0.0]
        removed = []
        rgb = np.zeros((2, 2, 3), dtype=np.uint8)
        alpha = np.full((2, 2), 255, dtype=np.uint8)
        store = ImageStore(max_images=2, max_bytes=32, ttl_seconds=10,
                           clock=lambda: now[0], on_remove=removed.append)
        store.put('A', rgb, alpha); store.put('B', rgb, alpha)
        store.get('A'); store.put('C', rgb, alpha)
        self.assertEqual(list(store.entries), ['A', 'C'])
        self.assertEqual(store.total_bytes, 32)
        with self.assertRaises(ImageUnavailable) as caught:
            store.get('B')
        self.assertEqual(caught.exception.code, 'IMAGE_EVICTED')
        with store.using('A'):
            now[0] = 11.0
            store.prune()
            self.assertIn('A', store.entries)
            self.assertNotIn('C', store.entries)
        self.assertEqual(store.get('A')['accessed'], 11.0)
        now[0] = 22.0
        with self.assertRaises(ImageUnavailable) as caught:
            store.get('A')
        self.assertEqual(caught.exception.code, 'IMAGE_EXPIRED')
        self.assertEqual(store.total_bytes, 0)
        self.assertEqual(set(removed), {'A', 'B', 'C'})
        tiny = ImageStore(max_images=1, max_bytes=16)
        tiny.put('A', rgb, alpha)
        with tiny.using('A'):
            with self.assertRaisesRegex(ValueError, 'IMAGE_STORE_BUSY'):
                tiny.put('B', rgb, alpha)
        with self.assertRaisesRegex(ValueError, 'IMAGE_TOO_LARGE_FOR_STORE'):
            tiny.put('big', np.zeros((4, 4, 3), dtype=np.uint8), np.zeros((4, 4), dtype=np.uint8))

    def test_icc_valid_absent_broken_and_orientation(self):
        source = Image.new('RGB', (12, 8), (37, 82, 141))
        for profile, status in [(None, 'assumed-srgb'),
                                (ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes(), 'converted-to-srgb'),
                                (b'not-an-icc-profile', 'invalid-icc-assumed-srgb')]:
            candidate = source.copy()
            if profile is not None:
                candidate.info['icc_profile'] = profile
            rgba, _, _, info = normalize_image(candidate)
            self.assertEqual(info['colorProfile'], status)
            np.testing.assert_allclose(np.asarray(rgba)[0, 0, :3], [37, 82, 141], atol=1)
        oriented = Image.new('RGB', (2, 3), 'red')
        oriented.getexif()[274] = 6
        self.assertEqual(normalize_image(oriented)[0].size, (3, 2))

    def test_premultiplied_resize_ignores_hidden_transparent_cyan(self):
        data = np.zeros((64, 64, 4), dtype=np.uint8)
        data[:, :32] = [255, 0, 0, 255]
        data[:, 32:] = [0, 255, 255, 0]
        rgba, segmentation, alpha, info = normalize_image(Image.fromarray(data), max_edge=16)
        result = np.asarray(rgba)
        self.assertEqual(rgba.size, (16, 16))
        visible = result[alpha > 0]
        self.assertTrue(len(visible) > 0)
        self.assertTrue(np.all(visible[:, 0] >= 250))
        self.assertTrue(np.all(visible[:, 1:3] <= 1))
        self.assertTrue(np.all(result[alpha == 0, :3] == 0))
        self.assertTrue(np.all(segmentation[alpha == 0] == 255))
        self.assertEqual(info['alphaResize'], 'premultiplied')


class BackendLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['BEAD_DISABLE_SAM'] = '1'
        import app
        cls.service = app

    def test_predictor_a_b_a_reencodes_and_eviction_invalidates(self):
        from types import SimpleNamespace
        service = self.service
        class Predictor:
            def __init__(self): self.encoded = []
            def set_image(self, rgb): self.encoded.append(int(rgb[0, 0, 0]))
            def predict(self, **kwargs): return np.ones((1, 16, 16), dtype=bool), None, None
        fake = Predictor()
        registry = ImageStore(max_images=2, max_bytes=10000, on_remove=service.invalidate_encoding)
        for key, value in [('A', 11), ('B', 22)]:
            registry.put(key, np.full((16,16,3),value,np.uint8), np.full((16,16),255,np.uint8))
        with patch.object(service,'store',registry), patch.object(service,'predictor',fake), patch.object(service,'device','CPU'), patch.object(service,'torch',SimpleNamespace(inference_mode=nullcontext)), patch.object(service,'encoded_image_id',None):
            for key in ['A','A','B','A']:
                result = service.segment(service.SegmentRequest(imageId=key,box=(1,1,15,15),revision=1))
                self.assertEqual(result['imageId'],key)
            self.assertEqual(fake.encoded,[11,22,11])
            registry._remove('A','IMAGE_EVICTED')
            self.assertIsNone(service.encoded_image_id)

    def test_real_grabcut_upload_and_invalid_input(self):
        from fastapi import HTTPException
        service = self.service
        service.cv2.setNumThreads(1)
        # Direct async read avoids testing Starlette's threadpool adapter itself.
        class InMemoryUpload:
            def __init__(self, contents): self.contents = contents
            async def read(self, limit): return self.contents[:limit]
        rgba = np.full((64,64,4),255,np.uint8)
        rgba[16:48,16:48,:3] = [220,40,40]
        buffer = io.BytesIO(); Image.fromarray(rgba).save(buffer,format='PNG')
        with patch.object(service,'store',ImageStore()),patch.object(service,'predictor',None):
            uploaded = asyncio.run(service.upload(InMemoryUpload(buffer.getvalue())))
            self.assertEqual((uploaded['width'],uploaded['height']),(64,64))
            result = service.segment(service.SegmentRequest(imageId=uploaded['imageId'],box=(8,8,56,56),points=[service.Point(x=32,y=32,label=1)],revision=2))
            decoded = np.asarray(Image.open(io.BytesIO(base64.b64decode(result['mask'].split(',')[1]))))
            self.assertEqual(decoded.shape,(64,64));self.assertEqual(int(decoded[32,32]),255);self.assertEqual(int(decoded[0,0]),0)
            with self.assertRaises(HTTPException) as caught:
                service.segment(service.SegmentRequest(imageId=uploaded['imageId'],box=(0,0,1,1),revision=3))
            self.assertEqual(caught.exception.status_code,400)
            with self.assertRaises(HTTPException):
                asyncio.run(service.upload(InMemoryUpload(b'not-image')))


if __name__ == '__main__':
    unittest.main(verbosity=2)


