"""Source colors for display/sampling remain separate from segmentation RGB."""
from __future__ import annotations

import io
import numpy as np
from PIL import Image, ImageCms, ImageOps

NORMALIZATION_VERSION = 'srgb-premultiplied-v1'


def normalize_image(source: Image.Image, max_edge=1536):
    oriented = ImageOps.exif_transpose(source)
    alpha = oriented.convert('RGBA').getchannel('A')
    icc = oriented.info.get('icc_profile')
    profile_status = 'assumed-srgb'
    color = oriented.convert('RGB')
    if icc:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            # Preserve a CMYK or grayscale input mode compatible with its ICC profile.
            profile_input = oriented if oriented.mode in ('RGB', 'CMYK', 'L', 'LAB') else color
            color = ImageCms.profileToProfile(profile_input, profile, ImageCms.createProfile('sRGB'), outputMode='RGB')
            profile_status = 'converted-to-srgb'
        except (ImageCms.PyCMSError, OSError, ValueError, TypeError):
            profile_status = 'invalid-icc-assumed-srgb'
    rgba = color.convert('RGBA')
    rgba.putalpha(alpha)
    if max(rgba.size) > max_edge:
        # RGBa stores premultiplied channels, preventing hidden transparent RGB
        # from being interpolated into visible edge colors by LANCZOS.
        premultiplied = rgba.convert('RGBa')
        premultiplied.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        rgba = premultiplied.convert('RGBA')
    data = np.array(rgba)
    data[data[:, :, 3] == 0, :3] = 0
    rgba = Image.fromarray(data)
    segmentation = Image.new('RGB', rgba.size, 'white')
    segmentation.paste(rgba, mask=rgba.getchannel('A'))
    return rgba, np.array(segmentation), data[:, :, 3].copy(), {
        'version': NORMALIZATION_VERSION,
        'colorProfile': profile_status,
        'alphaResize': 'premultiplied',
    }
