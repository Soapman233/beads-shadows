"""Populate a synthetic MySQL project, back it up offline, and open its restore."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import mkdtemp
from urllib.error import URLError
from urllib.parse import urlsplit
from uuid import uuid4
import argparse
import io
import os
import secrets
import socket
import subprocess
import sys
import time

from PIL import Image
from mysql_platform_test import Client, png

ROOT = Path(__file__).resolve().parents[1]


def run(module, env, *args):
    result = subprocess.run([sys.executable, "-m", module, *map(str, args)],
                            cwd=ROOT / "backend", env=env, capture_output=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        output = result.stderr.decode("utf-8", errors="replace")
        for key in ("BEAD_DATABASE_URL", "BEAD_BACKUP_SOURCE_URL", "BEAD_BACKUP_TARGET_URL"):
            value = env.get(key)
            if value:
                secret = urlsplit(value).password
                if secret:
                    output = output.replace(secret, "[redacted]")
        raise RuntimeError(f"{module} failed ({result.returncode}): {output}")


@contextmanager
def service(env, log_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    client = Client(f"http://127.0.0.1:{port}")
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app:app", "--app-dir", "backend",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    ready = False
    try:
        for _ in range(40):
            if process.poll() is not None:
                break
            try:
                client.request("GET", "/health")
                ready = True
                break
            except (URLError, TimeoutError):
                time.sleep(0.2)
        if not ready:
            raise RuntimeError(f"Backend did not become ready. See {log_path}")
        yield client
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def scoped_env(name, assets):
    key = "BEAD_BACKUP_SOURCE_URL" if name == "source" else "BEAD_BACKUP_TARGET_URL"
    value = os.environ.get(key, "")
    url = urlsplit(value)
    if url.scheme != "mysql+pymysql" or url.hostname != "127.0.0.1" or url.path != f"/bead_backup_{name}":
        raise ValueError(f"{key} must designate isolated database bead_backup_{name} on the local test instance")
    return {**os.environ, "BEAD_DATABASE_URL": value, "BEAD_ASSET_DIR": str(assets),
            "BEAD_DISABLE_SAM": "1", "BEAD_AI_ENABLED": "0"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mysql-bin", required=True, type=Path)
    args = parser.parse_args()
    runtime = ROOT / "tmp"
    runtime.mkdir(exist_ok=True)
    stage = Path(mkdtemp(prefix="backup-proof-", dir=runtime))
    source_env = scoped_env("source", stage / "source-assets")
    target_env = scoped_env("target", stage / "restored-assets")
    run("alembic", source_env, "upgrade", "head")
    username = f"test-restore-{uuid4().hex[:8]}"
    password = secrets.token_urlsafe(20)
    with service(source_env, stage / "source-server.log") as source:
        source.register(username, password)
        source_id = source.request("POST", "/assets", status=201, multipart=(png("red"), "source"))["id"]
        mask_id = source.request("POST", "/assets", status=201, multipart=(png("black"), "mask"))["id"]
        project = source.request("POST", "/projects", {
            "request_id": uuid4().hex, "name": "恢复演练", "source_id": source_id, "mask_id": mask_id,
            "project": {"schemaVersion": 2, "pattern": {
                "width": 2, "height": 1, "cells": ["W1", None],
                "palette": [{"code": "W1", "hex": "#FFFFFF"}], "colorLimit": 1,
            }},
        }, 201)
        path = f"/projects/{project['id']}"
        expected = source.request("GET", path)
        originals = {asset_id: source.request("GET", f"/assets/{asset_id}/content")
                     for asset_id in (source_id, mask_id)}
    # Both application instances remain stopped during the database and asset transfer.
    bundle = stage / "backup.zip"
    suffix = ".exe" if os.name == "nt" else ""
    run("platform_api.backup", source_env, "backup", bundle, "--offline",
        "--program", args.mysql_bin / ("mysqldump" + suffix))
    run("platform_api.backup", target_env, "restore", bundle, "--offline",
        "--program", args.mysql_bin / ("mysql" + suffix))
    with service(target_env, stage / "restore-server.log") as restored:
        restored.login(username, password)
        assert restored.request("GET", path) == expected
        for asset_id, mode, color in [(source_id, "RGBA", (255, 0, 0, 255)), (mask_id, "L", 0)]:
            image = restored.request("GET", f"/assets/{asset_id}/content")
            assert image == originals[asset_id]
            with Image.open(io.BytesIO(image)) as decoded:
                assert decoded.convert(mode).getpixel((32, 32)) == color
    print("Backup restored: project, exact version and private source/mask readable through HTTP.")


if __name__ == "__main__":
    main()
