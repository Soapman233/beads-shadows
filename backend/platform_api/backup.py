"""Offline backup and restore of an isolated MySQL schema and its private images."""
from argparse import ArgumentParser
from fnmatch import fnmatchcase
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import inspect, select

from .db import database_url, session_factory
from .projects import Asset, asset_path

PNG_NAME = re.compile(r'[a-f0-9-]{36}\.png')


def mysql_cmd(program, args, **streams):
    url = database_url()
    child_env = dict(os.environ)
    child_env.pop('BEAD_DATABASE_URL', None)
    child_env['MYSQL_PWD'] = url.password or ''
    command = [program, '--protocol=TCP', '--host=' + (url.host or '127.0.0.1'),
               '--port=' + str(url.port or 3306), '--user=' + (url.username or ''),
               '--default-character-set=utf8mb4', *args, '--', url.database]
    subprocess.run(command, env=child_env, check=True, **streams)


def database_assets():
    with session_factory()() as db:
        return [(row.id + '.png', row.size) for row in db.scalars(select(Asset))]


def backup(destination, dump_program):
    files = database_assets()
    folder = asset_path('00000000-0000-0000-0000-000000000000').parent
    for name, size in files:
        if not PNG_NAME.fullmatch(name) or not (folder / name).is_file() or (folder / name).stat().st_size != size:
            raise ValueError('An asset could not be read. Check the configured private asset folder.')
    with TemporaryDirectory() as stage:
        sql = Path(stage) / 'database.sql'
        with sql.open('wb') as stream:
            mysql_cmd(dump_program, ['--single-transaction', '--no-tablespaces', '--skip-triggers',
                                      '--set-gtid-purged=OFF', '--hex-blob'], stdout=stream)
        with ZipFile(destination, 'x', ZIP_DEFLATED, compresslevel=3) as archive:
            archive.write(sql, 'database.sql')
            for name, _ in files:
                archive.write(folder / name, 'assets/' + name)


def restore(source, mysql_program):
    # Never restore over live project data. Use an empty target and an unused folder.
    factory = session_factory()
    with factory() as db:
        if inspect(db.connection()).get_table_names():
            raise ValueError('Restore requires an empty target database.')
    folder = asset_path('00000000-0000-0000-0000-000000000000').parent
    if folder.exists():
        raise ValueError('Restore requires a new asset directory path.')
    with TemporaryDirectory(dir=folder.parent) as stage, ZipFile(source) as archive:
        names = archive.namelist()
        if (len(names) != len(set(names)) or 'database.sql' not in names
                or any(n != 'database.sql' and not (n.startswith('assets/') and PNG_NAME.fullmatch(n[7:])) for n in names)):
            raise ValueError('Unexpected bundle structure.')
        data_dir = Path(stage) / 'assets'
        data_dir.mkdir()
        for name in names:
            target = Path(stage) / 'database.sql' if name == 'database.sql' else data_dir / name[7:]
            with archive.open(name) as inp, target.open('xb') as out:
                shutil.copyfileobj(inp, out)
        # Restore only trusted, locally created dumps. The SQL runs with the target schema account.
        with (Path(stage) / 'database.sql').open('rb') as stream:
            mysql_cmd(mysql_program, [], stdin=stream)
        expected = dict(database_assets())
        if ({path.name for path in data_dir.iterdir()} != set(expected)
                or any((data_dir / name).stat().st_size != size for name, size in expected.items())):
            raise ValueError('Asset references are incomplete. Discard the isolated restore target and retry.')
        data_dir.rename(folder)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('backup', 'restore'))
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--program', help='Path to mysqldump for backup or mysql for restore')
    parser.add_argument('--offline', required=True, action='store_true', help='Confirm the platform is offline during maintenance')
    args = parser.parse_args()
    if args.operation == 'backup':
        backup(args.bundle, args.program or 'mysqldump')
    else:
        if not os.environ.get('BEAD_ASSET_DIR'):
            parser.error('Restore requires an explicit BEAD_ASSET_DIR')
        restore(args.bundle, args.program or 'mysql')
    print('完成。请使用独立环境核验项目与私有资源。')


if __name__ == '__main__':
    main()
