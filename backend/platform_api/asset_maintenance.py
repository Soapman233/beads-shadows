"""Report or quarantine old unreferenced private images while the app is offline."""
from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
from tempfile import mkdtemp

from sqlalchemy import delete, select

from .ai_jobs import AIJob
from .db import session_factory
from .extensions import BuildCompletion
from .projects import Asset, ProjectVersion


ASSET_FILE = re.compile(r'([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\.(png|pending)')


def orphaned_assets(db, directory, cutoff):
    references = (ProjectVersion.source_id, ProjectVersion.mask_id, AIJob.input_id,
                  AIJob.output_id, BuildCompletion.photo_id)
    unreferenced = select(Asset.id).where(Asset.created_at < cutoff, *(
        ~select(column).where(column == Asset.id).exists() for column in references
    ))
    eligible = set(db.scalars(unreferenced))
    registered = set(db.scalars(select(Asset.id)))
    threshold = cutoff.replace(tzinfo=timezone.utc).timestamp()
    files = []
    rows = []
    for path in directory.iterdir():
        match = ASSET_FILE.fullmatch(path.name)
        if not match or path.is_symlink() or not path.is_file() or path.stat().st_mtime >= threshold:
            continue
        asset_id, suffix = match.groups()
        if asset_id not in registered or (asset_id in eligible and suffix == 'png'):
            files.append(path)
            if asset_id in eligible:
                rows.append(asset_id)
    return files, rows


def maintain(directory, cutoff, *, apply=False):
    directory = directory.resolve(strict=True)
    with session_factory()() as db:
        files, rows = orphaned_assets(db, directory, cutoff)
        if apply and files:
            quarantine = Path(mkdtemp(prefix='quarantine-', dir=directory))
            if rows:
                db.execute(delete(Asset).where(Asset.id.in_(rows)))
            # Unmoved files remain discoverable if the process stops after the commit.
            db.commit()
            for path in files:
                path.rename(quarantine / path.name)
    return len(files), len(rows)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--offline', required=True, action='store_true')
    parser.add_argument('--apply', action='store_true', help='Move files into quarantine and release their unused quota')
    parser.add_argument('--days', default=7, type=int)
    args = parser.parse_args()
    path = os.environ.get('BEAD_ASSET_DIR')
    if not path:
        parser.error('Set BEAD_ASSET_DIR to the dedicated asset directory of the selected database')
    if not 1 <= args.days <= 3650:
        parser.error('--days must be between 1 and 3650')
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=args.days)
    files, rows = maintain(Path(path), cutoff, apply=args.apply)
    print(f'{"已隔离" if args.apply else "待隔离"} {files} 个文件，涉及 {rows} 条未引用资产记录。')


if __name__ == '__main__':
    main()
