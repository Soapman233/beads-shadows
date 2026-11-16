"""Bounded in-process image registry; its caller holds the shared inference lock."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import time


class ImageUnavailable(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ImageStore:
    def __init__(self, max_images=8, max_bytes=64 * 1024 * 1024, ttl_seconds=1800,
                 clock=time.monotonic, on_remove=None):
        if max_images < 1 or max_bytes < 1 or ttl_seconds <= 0:
            raise ValueError('Image store limits must be positive')
        self.max_images, self.max_bytes, self.ttl_seconds = max_images, max_bytes, ttl_seconds
        self.clock, self.on_remove = clock, on_remove
        self.entries = OrderedDict()
        self.removed = OrderedDict()
        self.total_bytes = 0
        self.active_id = None

    def _remove(self, image_id, reason):
        entry = self.entries.pop(image_id)
        self.total_bytes -= entry['bytes']
        self.removed[image_id] = reason
        self.removed.move_to_end(image_id)
        while len(self.removed) > 128:
            self.removed.popitem(last=False)
        if self.on_remove:
            self.on_remove(image_id)

    def prune(self):
        now = self.clock()
        for image_id, entry in list(self.entries.items()):
            if image_id != self.active_id and now - entry['accessed'] >= self.ttl_seconds:
                self._remove(image_id, 'IMAGE_EXPIRED')

    def put(self, image_id, rgb, alpha, normalization=None):
        size = rgb.nbytes + alpha.nbytes
        if size > self.max_bytes:
            raise ValueError('IMAGE_TOO_LARGE_FOR_STORE')
        self.prune()
        if image_id in self.entries:
            raise ValueError('Duplicate image ID')
        while len(self.entries) >= self.max_images or self.total_bytes + size > self.max_bytes:
            victim = next((key for key in self.entries if key != self.active_id), None)
            if victim is None:
                raise ValueError('IMAGE_STORE_BUSY')
            self._remove(victim, 'IMAGE_EVICTED')
        self.entries[image_id] = dict(rgb=rgb, alpha=alpha, bytes=size,
                                      accessed=self.clock(), normalization=normalization)
        self.total_bytes += size

    def get(self, image_id):
        self.prune()
        if image_id not in self.entries:
            raise ImageUnavailable(self.removed.get(image_id, 'IMAGE_NOT_FOUND'))
        entry = self.entries[image_id]
        entry['accessed'] = self.clock()
        self.entries.move_to_end(image_id)
        return entry

    @contextmanager
    def using(self, image_id):
        entry = self.get(image_id)
        previous, self.active_id = self.active_id, image_id
        try:
            yield entry
        finally:
            # Idle TTL starts after inference completes, not when it began.
            entry['accessed'] = self.clock()
            self.active_id = previous

