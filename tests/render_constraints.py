"""Small public-data contact sheets. No screenshot comparison or hashes."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / 'experiments/generated'
for name in ['astronaut', 'coffee', 'synthetic-6', 'rocket', 'camera']:
    payload = json.loads((root / f'{name}-constraints-preview.json').read_text(encoding='utf-8'))
    data = payload['input']
    source = Image.frombytes('RGBA', (data['width'], data['height']), bytes(data['rgba']))
    board = Image.new('RGB', (1000, 300), 'white')
    draw = ImageDraw.Draw(board)
    source.thumbnail((190, 250))
    board.paste(source, (0, 30), source)
    draw.text((4, 8), name + ' source', fill='black')
    for column, variant in enumerate(['default', 'required', 'roi', 'combined'], 1):
        pattern = payload['patterns'][variant]
        colors = {color['code']: color['hex'] for color in pattern['palette']}
        image = Image.new('RGB', (pattern['width'], pattern['height']), '#DDDDDD')
        pixel = image.load()
        for index, code in enumerate(pattern['cells']):
            if code is not None:
                pixel[index % image.width, index // image.width] = tuple(bytes.fromhex(colors[code][1:]))
        image = image.resize((192, round(192 * image.height / image.width)), Image.Resampling.NEAREST)
        board.paste(image, (column * 200, 30))
        draw.text((column * 200 + 4, 8), variant, fill='black')
    board.save(root / f'{name}-constraints.png')
    print(name + '-constraints.png')
