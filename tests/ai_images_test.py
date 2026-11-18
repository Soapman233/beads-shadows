"""Contract tests only: no paid calls, no secrets or user images."""
import base64
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from PIL import Image
from fastapi import HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import ai_images as ai

class BailianTest(unittest.TestCase):
    def test_disabled_and_consent_never_call_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(ai, 'read_remote') as call:
            self.assertFalse(ai.capabilities()['available'])
            with self.assertRaises(HTTPException) as e: ai.edit(ai.EditRequest(image='x', prompt='x'))
            self.assertEqual(e.exception.status_code, 503); call.assert_not_called()
        with patch.object(ai, 'settings', return_value=(True, 'unused', 'test')), patch.object(ai, 'read_remote') as call:
            with self.assertRaises(HTTPException) as e: ai.edit(ai.EditRequest(image='x', prompt='x'))
            self.assertEqual(e.exception.status_code, 400); call.assert_not_called()

    def test_mocked_response_and_single_image_contract(self):
        out = io.BytesIO(); Image.new('RGB', (16, 16), 'blue').save(out, format='PNG')
        image = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()
        response = {'output': {'choices': [{'message': {'content': [{'image': 'https://example.oss-cn-beijing.aliyuncs.com/generated.png'}]}}]}}
        with patch.object(ai, 'settings', return_value=(True, 'https://example.cn-beijing.maas.aliyuncs.com' + ai.SUFFIX, 'test-only')), patch.object(ai, 'read_remote', side_effect=[json.dumps(response).encode(), out.getvalue()]) as call:
            result = ai.edit(ai.EditRequest(image=image, prompt='pixel art', consent=True))
            self.assertTrue(result['image'].startswith('data:image/png;base64,'))
            self.assertEqual(call.call_count, 2)
            sent = json.loads(call.call_args_list[0].args[0].data)
            self.assertEqual(sent['parameters']['n'], 1)
            self.assertEqual(sent['model'], 'qwen-image-edit-plus')

    def test_reject_non_provider_result(self):
        body = {'output': {'choices': [{'message': {'content': [{'image': 'http://127.0.0.1/private'}]}}]}}
        with self.assertRaises(ValueError): ai.result_url(body)

if __name__ == '__main__': unittest.main()
