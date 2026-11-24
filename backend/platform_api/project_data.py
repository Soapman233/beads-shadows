"""Validate persisted v2 project data independently of the browser."""
import re
from collections import Counter
from typing import Any
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt


class ProjectBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1, max_length=80)
    project: dict[str, Any]
    source_id: str | None = Field(None, max_length=36)
    mask_id: str | None = Field(None, max_length=36)


class CreateProject(ProjectBody):
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')


class UpdateProject(ProjectBody):
    expected_revision: StrictInt = Field(ge=1)


class RevisionRequest(BaseModel):
    expected_revision: StrictInt = Field(ge=1)


PROJECT_FIELDS = ('normalization', 'paletteId', 'constraints', 'pattern', 'box',
                  'points', 'locked', 'step', 'pitch', 'selectionMode', 'selectionDirty', 'tuning')
PATTERN_FIELDS = ('width', 'height', 'cells', 'palette', 'colorLimit', 'paletteId',
                  'paletteName', 'paletteInfo', 'algorithm', 'sampling', 'constraints')


def bad_project():
    raise HTTPException(422, '项目数据无效')


def integers_between(value, low, high):
    return type(value) is int and low <= value <= high


def finite_coordinate(value):
    return type(value) in (int, float) and 0 <= value <= 1536


def validate_pattern(pattern):
    if not isinstance(pattern, dict):
        bad_project()
    width, height = pattern.get('width'), pattern.get('height')
    palette, cells, limit = pattern.get('palette'), pattern.get('cells'), pattern.get('colorLimit')
    if (not integers_between(width, 1, 128) or not integers_between(height, 1, 128)
            or width * height > 8192 or not isinstance(cells, list) or len(cells) != width * height
            or not integers_between(limit, 1, 512) or not isinstance(palette, list) or not 1 <= len(palette) <= limit):
        bad_project()
    colors = {}
    for color in palette:
        code = color.get('code') if isinstance(color, dict) else None
        hex_value = color.get('hex') if isinstance(color, dict) else None
        if (not isinstance(code, str) or not 1 <= len(code) <= 40 or code in colors
                or code in ('__proto__', 'constructor', 'prototype')
                or not isinstance(hex_value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', hex_value)):
            bad_project()
        colors[code] = hex_value
    if any(cell is not None and (not isinstance(cell, str) or cell not in colors) for cell in cells):
        bad_project()
    clean = {key: pattern[key] for key in PATTERN_FIELDS if key in pattern}
    clean['palette'] = [{'code': code, 'hex': hex_value} for code, hex_value in colors.items()]
    validate_options(clean)
    if 'paletteInfo' in clean:
        info = clean['paletteInfo']
        keys = ('brand', 'series', 'version', 'source', 'license', 'note')
        if not isinstance(info, dict) or any(not isinstance(info.get(k), str) or len(info[k]) > 2000 for k in keys):
            bad_project()
        clean['paletteInfo'] = {key: info[key] for key in keys}
    if 'sampling' in clean and clean['sampling'] not in ('mean', 'dominant'):
        bad_project()
    return clean, Counter(c for c in cells if c is not None)


def validate_options(data):
    for key, size in [('paletteId', 100), ('paletteName', 200), ('algorithm', 100), ('normalization', 100)]:
        if key in data and (not isinstance(data[key], str) or len(data[key]) > size):
            bad_project()
    if 'constraints' in data:
        val = data['constraints']
        if not isinstance(val, dict):
            bad_project()
        required, roi, weight = val.get('required', []), val.get('roi'), val.get('weight', 3)
        if (not isinstance(required, list) or len(required) > 4
                or any(not isinstance(code, str) or len(code) > 40 for code in required)
                or type(weight) not in (int, float) or not 1 <= weight <= 4):
            bad_project()
        if roi is not None and (not isinstance(roi, list) or len(roi) != 4
                                or any(type(n) not in (int, float) or not 0 <= n <= 1 for n in roi)
                                or roi[0] >= roi[2] or roi[1] >= roi[3]):
            bad_project()
        data['constraints'] = {'required': required, 'weight': weight}
        if roi is not None:
            data['constraints']['roi'] = roi


def validate_project(raw, source_size, mask_size):
    if raw.get('schemaVersion') != 2 or 'source' in raw or 'mask' in raw:
        bad_project()
    data = {'schemaVersion': 2, **{key: raw[key] for key in PROJECT_FIELDS if key in raw}}
    counts = Counter()
    if 'pattern' in data:
        data['pattern'], counts = validate_pattern(data['pattern'])
    if not source_size and 'pattern' not in data:
        bad_project()
    if mask_size and mask_size != source_size:
        bad_project()
    points, box, locked = data.get('points', []), data.get('box'), data.get('locked', [])
    if not isinstance(points, list) or len(points) > 1000:
        bad_project()
    clean_points = []
    for p in points:
        if (not isinstance(p, dict) or not all(finite_coordinate(p.get(k)) for k in ('x', 'y'))
                or not integers_between(p.get('label'), 0, 1)
                or (source_size and (p['x'] >= source_size[0] or p['y'] >= source_size[1]))):
            bad_project()
        clean_points.append({k: p[k] for k in ('x', 'y', 'label')})
    data['points'] = clean_points
    if box is not None and (not isinstance(box, list) or len(box) != 4 or not all(map(finite_coordinate, box))
                            or box[0] >= box[2] or box[1] >= box[3]
                            or (source_size and (box[2] > source_size[0] or box[3] > source_size[1]))):
        bad_project()
    codes = {c['code'] for c in data.get('pattern', {}).get('palette', [])}
    if not isinstance(locked, list) or any(not isinstance(c, str) or c not in codes for c in locked):
        bad_project()
    data['locked'] = list(dict.fromkeys(locked))
    if not integers_between(data.get('step', 1), 1, 3) or data.get('pitch', 2.6) not in (2.6, 5):
        bad_project()
    if data.get('selectionMode', 'whole') not in ('whole', 'object') or type(data.get('selectionDirty', False)) is not bool:
        bad_project()
    if 'tuning' in data:
        tuning = data['tuning']
        if (not isinstance(tuning, dict) or tuning.get('width') not in (32, 48, 64)
                or tuning.get('colors') not in (8, 12, 16, 24, 32)):
            bad_project()
        data['tuning'] = {k: tuning[k] for k in ('width', 'colors')}
    validate_options(data)
    return data, counts
