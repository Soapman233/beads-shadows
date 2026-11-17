# Real image sources

Downloaded 2026-11-15 from scikit-image v0.25.2 data, without active hash verification.

- person.png: astronaut Eileen Collins, NASA public domain. https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/astronaut.png
- pet.png: Chelsea cat, CC0 photographer Stefan van der Walt. https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/chelsea.png
- object.png: coffee cup, CC0 photographer Rachel Michetti, courtesy Pikolo Espresso Bar. https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/coffee.png

License and attribution evidence: https://scikit-image.org/docs/stable/api/skimage.data.html (astronaut, chelsea, coffee sections).
The astronaut scene contains equipment and a complex background. Coffee includes textured wood and multiple objects. Real images test quality; synthetic fixture only tests logic.

## 2026-11-17 additions

Six additional real photographs downloaded directly from the pinned scikit-image v0.25.2 repository. Images were decoded with Pillow to check dimensions; no active hash verification was performed. Original image bytes retained; clock filename shortened locally.

| Local file | Upstream filename | Pixels | Attribution / license documented upstream | Category |
|---|---|---|---|---|
| brick.png | brick.png | 512 × 512 | CC0Textures, CC0 | wall texture |
| grass.png | grass.png | 512 × 512 | DeviantArt original, CC0 | vegetation texture |
| gravel.png | gravel.png | 512 × 512 | CC0Textures, CC0 | stones texture |
| camera.png | camera.png | 512 × 512 | Lav Varshney, CC0 | person with camera |
| clock.png | clock_motion.png | 400 × 300 | Stefan van der Walt, public domain | motion-blurred object |
| rocket.jpg | rocket.jpg | 640 × 427 | SpaceX, public domain | color scene / complex background |

[Official per-image license documentation](https://scikit-image.org/docs/0.25.x/api/skimage.data.html) (brick, grass, gravel, camera, clock, rocket sections).
[Official pinned fetcher source](https://github.com/scikit-image/scikit-image/blob/v0.25.2/skimage/data/_fetchers.py).

Download URLs are `https://raw.githubusercontent.com/scikit-image/scikit-image/v0.25.2/skimage/data/` plus the upstream filename in the table. Grass and brick were already cropped/transformed/grayscaled upstream; this repository did not create synthetic variants and count them as new photos.

These six additions are five grayscale photographs and one RGB photograph. Together with the original three RGB photographs they provide nine real images, but do not provide balanced illustration/color coverage. Do not claim they replace a licensed color illustration evaluation set. Split development/holdout and fix ROI in the experiment manifest before evaluating new policies; these files alone are not evaluation results.
