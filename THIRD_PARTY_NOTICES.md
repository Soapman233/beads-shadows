# Third-party notices

## Palette data included in this repository

- Project: maxcleme/beadcolors
- Source: https://github.com/maxcleme/beadcolors/blob/master/raw/mard.csv
- License: MIT, Copyright (c) 2020 maxcleme
- Included notice: frontend/src/palettes/LICENSE-beadcolors.txt
- Included data: frontend/src/palettes/mard-source.csv; derived 220-color subset: mard.ts
- Details: frontend/src/palettes/SOURCES.md

## Workflow references (not redistributed)

Zippland/perler-beads: https://github.com/Zippland/perler-beads (AGPL-3.0). Referenced the generation / refinement workflow and source-target global color replacement interaction. No source code, components or palette mappings from that repository are included. The replacement logic here independently matches bead codes and enforces this project's saved palette provenance and edit history.

## Optional model (not redistributed)

Meta SAM 2: https://github.com/facebookresearch/sam2 . Obtain source and weights from the official project and follow its license and installation instructions. Neither model weights nor vendor source are bundled here. Base installation uses OpenCV GrabCut.

## Color-space reference

Oklab definition and published transforms: https://bottosson.github.io/posts/oklab/ . Current matching uses independently implemented numerical transforms and a project-specific hue-weighted objective, not a claim of standardized Delta E performance.

## Runtime dependencies

JavaScript dependency versions are recorded in frontend/package-lock.json. Python dependencies are listed in backend/requirements.txt. Dependencies remain subject to their own licenses; dependency distributions, virtual environments and node_modules are excluded from the repository.

## Test dependency and demonstration images

fake-indexeddb (Apache-2.0) is a development-only IndexedDB test implementation; installed via npm and recorded in package-lock.json. No source is vendored. License: https://github.com/dumbmatter/fakeIndexedDB/blob/master/LICENSE .

examples/dataset contains NASA public-domain astronaut and CC0 Chelsea/coffee images; attribution and pinned source URLs are in examples/dataset/SOURCES.md. examples/geometric.png is an original synthetic fixture, covered by this project license. No private user image is included.
