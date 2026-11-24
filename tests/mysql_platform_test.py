"""Run the P0 workflow against an isolated MySQL schema and real local HTTP.

Run after Alembic upgrade with BEAD_DATABASE_URL ending /beads_platform_test.
Each run creates synthetic users for isolation. Never run against user data.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import base64
from email.parser import BytesParser
from email.policy import default as email_policy
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from PIL import Image, ImageDraw


class Client:
    def __init__(self, origin):
        self.origin = origin
        self.cookies = CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))
        self.csrf = None
        self.account_hint = None

    def cookie_header(self):
        return "; ".join(f"{cookie.name}={cookie.value}" for cookie in self.cookies)

    def request(self, method, path, body=None, status=200, *, csrf=True, multipart=None):
        headers = {"Origin": self.origin}
        if self.account_hint:
            headers["X-Bead-Account"] = self.account_hint
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        data = None
        if multipart:
            contents, kind = multipart
            boundary = uuid4().hex
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            data = (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="sample.png"\r\n'
                'Content-Type: image/png\r\n\r\n'
            ).encode() + contents + b"\r\n"
            if kind is not None:
                data += f'--{boundary}\r\nContent-Disposition: form-data; name="kind"\r\n\r\n{kind}\r\n'.encode()
            data += f"--{boundary}--\r\n".encode()
        elif body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, allow_nan=False).encode()
        request = Request(f"{self.origin}/api{path}", data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            actual = response.code
            payload = response.read()
            if payload and response.headers.get_content_type() == "application/json":
                payload = json.loads(payload)
        if status is not None and actual != status:
            raise AssertionError(f"{method} {path}: expected {status}, got {actual}")
        return payload if status is not None else (actual, payload)

    def register(self, username, password):
        data = self.request("POST", "/auth/register", {"username": username, "password": password}, 201)
        self.csrf = data["csrfToken"]
        return data["user"]

    def login(self, username, password, status=200):
        data = self.request("POST", "/auth/login", {"username": username, "password": password}, status)
        if status == 200:
            self.csrf = data["csrfToken"]
        return data


def png(color, bounds=(16, 16, 47, 47)):
    image = Image.new("RGBA", (64, 64), "white")
    ImageDraw.Draw(image).rectangle(bounds, fill=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class MySQLPlatformTest(unittest.TestCase):
    def start_server(self):
        url = urlsplit(os.environ.get("BEAD_DATABASE_URL", ""))
        if url.scheme != "mysql+pymysql" or url.path != "/beads_platform_test" or url.hostname not in ("localhost", "127.0.0.1"):
            raise RuntimeError("BEAD_DATABASE_URL must target isolated local schema beads_platform_test")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        root = Path(__file__).resolve().parents[1]
        runtime = root / "tmp" / "mysql-platform-tests" / uuid4().hex
        runtime.mkdir(parents=True, exist_ok=False)
        self.outbox = runtime / "outbox"
        self.origin = f"http://127.0.0.1:{port}"
        env = {**os.environ, "BEAD_DISABLE_SAM": "1", "BEAD_AI_ENABLED": "0",
               "BEAD_AI_SIMULATION": "1", "BEAD_AI_PLATFORM_LIVE": "0", "BEAD_MOCK_PAYMENTS": "1",
               "BEAD_DEVELOPMENT_OUTBOX": str(self.outbox),
               "BEAD_ASSET_DIR": str(runtime / "assets"), "BEAD_WEB_ORIGIN": self.origin}
        with (runtime / "server.log").open("wb") as log:
            self.server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app:app", "--app-dir", "backend",
                 "--host", "127.0.0.1", "--port", str(port)],
                cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        self.addCleanup(self.stop_server)
        for _ in range(40):
            if self.server.poll() is not None:
                break
            try:
                Client(self.origin).request("GET", "/health")
                return
            except (URLError, TimeoutError):
                time.sleep(0.2)
        raise RuntimeError(f"Local app failed to start. See {runtime / 'server.log'}")

    def stop_server(self):
        if self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)

    def setUp(self):
        self.start_server()
        uid = uuid4().hex[:12]
        self.alice = Client(self.origin)
        self.bob = Client(self.origin)
        self.username = f"test-a-{uid}"
        self.password = secrets.token_urlsafe(20)
        self.alice_user = self.alice.register(self.username, self.password)
        self.bob_user = self.bob.register(f"test-b-{uid}", secrets.token_urlsafe(20))

    def create_admin(self):
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "backend"))
        try:
            from platform_api.create_admin import main
        finally:
            sys.path.pop(0)
        username = f"test-admin-{uuid4().hex[:12]}"
        password = secrets.token_urlsafe(20)
        with patch("sys.argv", ["create_admin", username]), patch("getpass.getpass", return_value=password):
            main()
        admin = Client(self.origin)
        self.assertEqual(admin.login(username, password)["user"]["role"], "admin")
        return admin

    def save_fixture(self, pattern=None, **fields):
        body = {"request_id": uuid4().hex, "name": "私有测试图纸",
                "project": {"schemaVersion": 2, "pattern": pattern or {
                    "width": 2, "height": 2, "cells": ["W1", "R1", "W1", None],
                    "palette": [{"code": "W1", "hex": "#FFFFFF"}, {"code": "R1", "hex": "#FF0000"}],
                    "colorLimit": 2,
                }, **fields.pop("project_fields", {})}, **fields}
        project = self.alice.request("POST", "/projects", body, 201)
        return self.alice.request("GET", f"/projects/{project['id']}")

    def publish_fixture(self, admin, project, *, allow_remix=False, approve=True):
        publication = self.alice.request("POST", "/publications", {
            "projectId": project["id"], "versionId": project["version"]["id"],
            "title": f"公开测试图纸 {uuid4().hex[:8]}", "category": "object",
            "allowDownload": False, "allowRemix": allow_remix, "rightsConfirmed": True,
        }, 201)
        if approve:
            admin.request("POST", f"/admin/publications/{publication['id']}/moderate",
                          {"action": "approve", "reason": "合成测试图纸"})
        return publication

    def test_palette_publication_identity_audit_and_account_freeze(self):
        admin = self.create_admin()
        self.bob.request("GET", "/admin/palettes", status=403)
        self.bob.account_hint = self.alice_user["id"]
        self.bob.request("GET", "/auth/me", status=409)
        self.bob.account_hint = None
        original = {"brand": f"Test {uuid4().hex[:8]}", "series": "Standard", "sizeMm": 5}
        palette = admin.request("POST", "/admin/palettes", original, 201)["id"]
        path = f"/admin/palettes/{palette}"
        v1 = {"version": "v1", "source": "https://example.test/fixture", "licenseStatus": "internal",
              "csv": "code,hex\nW1,#FFFFFF\nR1,#FF0000\n"}
        admin.request("POST", f"{path}/preview", {**v1, "csv": "code,hex\nW1,#FFFFFF\nW1,#000000\n"}, 422)
        admin.request("POST", f"{path}/preview", {**v1, "csv": "code,hex\nW1,#GGGGGG\n"}, 422)
        self.assertEqual(admin.request("POST", f"{path}/preview", v1)["count"], 2)
        draft = admin.request("POST", f"{path}/versions", v1, 201)
        self.bob.request("GET", f"/palettes/{draft['id']}", status=404)
        admin.request("POST", f"/admin/palette-versions/{draft['id']}/publish")
        first = self.bob.request("GET", f"/palettes/{draft['id']}")
        v2 = {**v1, "version": "v2", "csv": "code,hex\nW1,#F0F0F0\nR1,#FF1100\n",
              "reuseColorCodes": ["W1"]}
        self.assertEqual(admin.request("POST", f"{path}/preview", v2)["diff"]["changed"], ["R1", "W1"])
        second = admin.request("POST", f"{path}/versions", v2, 201)
        self.assertEqual(second["colors"][0]["stableColorKey"], first["colors"][0]["stableColorKey"])
        self.assertNotEqual(second["colors"][1]["stableColorKey"], first["colors"][1]["stableColorKey"])
        admin.request("POST", f"/admin/palette-versions/{second['id']}/publish")
        selected = [item["id"] for item in self.bob.request("GET", "/palettes") if item["paletteId"] == palette]
        self.assertEqual(selected, [second["id"]])
        retained = self.bob.request("GET", f"/palettes/{draft['id']}")
        self.assertEqual(retained["status"], "retired")
        self.assertEqual(retained["colors"], first["colors"])
        admin.request("POST", f"/admin/palette-versions/{second['id']}/retire")
        self.assertFalse(any(item["paletteId"] == palette for item in self.bob.request("GET", "/palettes")))
        user_path = f"/admin/users/{self.alice_user['id']}"
        self.bob.request("PATCH", user_path, {"status": "frozen", "reason": "test"}, 403)
        admin.request("PATCH", user_path, {"status": "frozen", "reason": "集成测试"})
        self.alice.request("GET", "/projects", status=401)
        self.alice.login(self.username, self.password, status=401)
        admin.request("PATCH", user_path, {"status": "active", "reason": "集成测试结束"})
        self.alice.request("GET", "/projects", status=401)
        self.alice.login(self.username, self.password)
        self.alice.request("GET", "/projects")
        logs = admin.request("GET", "/admin/audit")
        actions = {row["action"] for row in logs if row["targetId"] == self.alice_user["id"]}
        self.assertEqual(actions, {"user.frozen", "user.active"})

    def test_inventory_atomic_import_concurrent_issue_and_versioned_shortage(self):
        admin = self.create_admin()
        original = {"brand": f"Stock {uuid4().hex[:8]}", "series": "Standard", "sizeMm": 5}
        palette = admin.request("POST", "/admin/palettes", original, 201)["id"]
        draft = admin.request("POST", f"/admin/palettes/{palette}/versions", {
            "version": "v1", "source": "https://example.test/fixture", "licenseStatus": "internal",
            "csv": "code,hex\nW1,#FFFFFF\nR1,#FF0000\n",
        }, 201)
        admin.request("POST", f"/admin/palette-versions/{draft['id']}/publish")
        command = {"versionId": draft["id"], "requestId": uuid4().hex, "csv": "code,quantity,unitPrice\nW1,5,0.25\n"}
        imported = self.alice.request("POST", "/inventory/import", command, 201)
        item = imported["items"][0]["id"]
        self.assertEqual(self.alice.request("POST", "/inventory/import", command, 201), imported)
        self.alice.request("POST", "/inventory/import", {
            **command, "requestId": uuid4().hex, "csv": "code,quantity\nW1,2\nabsent,1\n",
        }, 422)
        self.assertEqual(self.alice.request("GET", "/inventory")[0]["quantity"], 5)
        self.assertEqual(self.bob.request("GET", "/inventory"), [])
        self.bob.request("GET", f"/inventory/{item}/movements", status=404)

        project = self.alice.request("POST", "/projects", {
            "request_id": uuid4().hex, "name": "备料测试",
            "project": {"schemaVersion": 2, "pattern": {
                "width": 2, "height": 2, "cells": ["W1", None, "W1", "R1"],
                "palette": [{"code": "W1", "hex": "#FFFFFF"}, {"code": "R1", "hex": "#FF0000"}],
                "colorLimit": 2, "paletteId": f"db:{draft['id']}",
            }},
        }, 201)
        path = f"/projects/{project['id']}"
        version = self.alice.request("GET", path)["version"]["id"]
        other_tab = Client(self.origin)
        other_tab.login(self.username, self.password)
        ready = threading.Barrier(2, timeout=5)
        debit = {"itemId": item, "quantity": 4, "kind": "issue", "projectVersionId": version}

        def issue(tab):
            order = {**debit, "requestId": uuid4().hex}
            ready.wait()
            return order, tab.request("POST", "/inventory/movements", order, None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(issue, self.alice)
            right = pool.submit(issue, other_tab)
            attempts = [left.result(), right.result()]
        self.assertEqual(sorted(status for _, (status, _) in attempts), [201, 409])
        accepted, (_, receipt) = next(row for row in attempts if row[1][0] == 201)
        self.assertEqual(self.alice.request("POST", "/inventory/movements", accepted, 201), receipt)
        self.alice.request("POST", "/inventory/movements", {**accepted, "quantity": 1}, 409)
        ledger = self.alice.request("GET", f"/inventory/{item}/movements")
        self.assertEqual(len(ledger), 2)
        self.assertEqual(sum(move["delta"] for move in ledger), 1)
        materials = self.alice.request("GET", f"{path}/versions/1/materials?reservePercent=25")
        by_code = {row["code"]: row for row in materials["rows"]}
        self.assertEqual(materials["beadCount"], 3)
        self.assertEqual((by_code["W1"]["needed"], by_code["W1"]["withReserve"], by_code["W1"]["onHand"],
                          by_code["W1"]["shortage"], by_code["W1"]["estimatedCost"]), (2, 3, 1, 2, "0.50"))
        self.assertIsNone(by_code["R1"]["estimatedCost"])
        self.assertEqual(self.alice.request("GET", "/inventory")[0]["quantity"], 1)

    def test_workshop_weighted_progress_and_moderated_publications(self):
        admin = self.create_admin()
        series = admin.request("POST", "/admin/palettes", {
            "brand": f"Workshop {uuid4().hex[:8]}", "series": "Standard", "sizeMm": 5,
        }, 201)["id"]
        palette = admin.request("POST", f"/admin/palettes/{series}/versions", {
            "version": "v1", "source": "https://example.test/workshop", "licenseStatus": "internal",
            "csv": "code,hex\nW1,#FFFFFF\n",
        }, 201)
        admin.request("POST", f"/admin/palette-versions/{palette['id']}/publish")
        stock = self.alice.request("POST", "/inventory/import", {
            "versionId": palette["id"], "requestId": uuid4().hex, "csv": "code,quantity\nW1,2\n",
        }, 201)["items"][0]
        asset = self.alice.request("POST", "/assets", status=201, multipart=(png("red"), "source"))["id"]
        mask = self.alice.request("POST", "/assets", status=201, multipart=(png("black"), "mask"))["id"]
        cells = [None] * (48 * 16)
        for index in (0, 1, 2, 32):
            cells[index] = "W1"
        body = {"name": "私人制作测试", "source_id": asset, "mask_id": mask,
                "project": {"schemaVersion": 2, "pattern": {
                    "width": 48, "height": 16, "cells": cells,
                    "paletteId": f"db:{palette['id']}",
                    "palette": [{"code": "W1", "hex": "#FFFFFF"}], "colorLimit": 1,
                }}}
        project = self.alice.request("POST", "/projects", {"request_id": uuid4().hex, **body}, 201)
        project_path = f"/projects/{project['id']}"
        version = self.alice.request("GET", project_path)["version"]["id"]
        materials_path = f"{project_path}/versions/1/materials"
        shortage = self.alice.request("GET", materials_path)
        self.assertEqual(shortage["versionId"], version)
        self.assertEqual([(row["needed"], row["onHand"], row["shortage"]) for row in shortage["rows"]], [(4, 2, 2)])
        movement = {"itemId": stock["id"], "projectVersionId": version}
        self.alice.request("POST", "/inventory/movements", {
            **movement, "kind": "stock_in", "quantity": 2, "requestId": uuid4().hex,
        }, 201)
        self.assertEqual(self.alice.request("GET", materials_path)["rows"][0]["shortage"], 0)
        issued = self.alice.request("POST", "/inventory/movements", {
            **movement, "kind": "issue", "quantity": 4, "requestId": uuid4().hex,
        }, 201)
        self.assertEqual((issued["movement"]["projectVersionId"], issued["item"]["quantity"]), (version, 0))
        build_request = {"projectId": project["id"], "versionId": version, "blockSize": 16, "requestId": uuid4().hex}
        self.bob.request("POST", "/builds", build_request, 404)
        build = self.alice.request("POST", "/builds", build_request, 201)
        self.assertEqual(self.alice.request("POST", "/builds", build_request, 201)["id"], build["id"])
        self.assertEqual([(b["x"], b["y"], b["beads"]) for b in build["blocks"]], [(0, 0, 3), (2, 0, 1)])
        build_path = f"/builds/{build['id']}"
        self.bob.request("GET", build_path, status=404)
        place = {"x": 0, "y": 0, "completed": True, "expectedRevision": 1}
        self.alice.request("PATCH", f"{build_path}/blocks", {**place, "x": 1}, 404)
        partial = self.alice.request("PATCH", f"{build_path}/blocks", place)
        self.assertEqual((partial["completedBeads"], partial["beadCount"], partial["status"]), (3, 4, "in_progress"))
        self.alice.request("PATCH", f"{build_path}/blocks", place, 409)
        fresh_tab = Client(self.origin)
        fresh_tab.login(self.username, self.password)
        finished = fresh_tab.request("PATCH", f"{build_path}/blocks", {**place, "x": 2, "expectedRevision": 2})
        self.assertEqual((finished["completedBeads"], finished["status"]), (4, "done"))
        publication = {"projectId": project["id"], "versionId": version,
                       "title": f"验收图纸 {uuid4().hex[:8]}", "category": "object",
                       "allowDownload": False, "allowRemix": False, "rightsConfirmed": True}
        self.alice.request("POST", "/publications", {**publication, "rightsConfirmed": False}, 422)
        submitted = self.alice.request("POST", "/publications", publication, 201)
        pub_path = f"/publications/{submitted['id']}"
        moderation_path = f"/admin{pub_path}/moderate"
        anon = Client(self.origin)
        for subpath in ("", "/preview", "/download"):
            anon.request("GET", pub_path + subpath, status=404)
        self.bob.request("POST", moderation_path, {"action": "approve", "reason": "review"}, 403)
        admin.request("POST", moderation_path, {"action": "approve", "reason": "合成测试图纸"})
        self.alice.request("PATCH", project_path, {
            "expected_revision": 1,
            **body,
            "project": {"schemaVersion": 2, "pattern": {
                **body["project"]["pattern"], "cells": [None, *cells[1:]],
            }},
        })
        resumed = fresh_tab.request("GET", build_path)
        self.assertEqual(resumed["pattern"]["cells"], cells)
        self.assertEqual(resumed["completedBeads"], 4)
        detail = anon.request("GET", pub_path)
        self.assertEqual(detail["beadCount"], 4)
        self.assertTrue({"pattern", "cells", "source_id", "mask_id", "projectId", "versionId"}.isdisjoint(detail))
        preview = anon.request("GET", f"{pub_path}/preview")
        with Image.open(io.BytesIO(preview)) as bitmap:
            self.assertEqual(bitmap.format, "PNG")
            self.assertGreaterEqual(bitmap.width, 48)
        anon.request("GET", f"{pub_path}/download", status=403)
        admin.request("GET", f"/assets/{asset}/content", status=404)
        self.bob.request("PUT", f"{pub_path}/favorite", status=204)
        self.bob.request("PUT", f"{pub_path}/favorite", status=204)
        self.assertEqual([item["id"] for item in self.bob.request("GET", "/favorites")["items"]], [submitted["id"]])
        self.assertEqual(anon.request("GET", pub_path)["favoriteCount"], 1)
        directory = anon.request("GET", "/publications?category=object&minWidth=48&maxWidth=48&sort=popular")
        self.assertIn(submitted["id"], [item["id"] for item in directory["items"]])
        report = self.bob.request("POST", f"{pub_path}/report", {"reason": "合成举报测试"}, 201)
        admin.request("POST", f"/admin/publication-reports/{report['id']}/resolve", {"reason": "受理测试"})
        admin.request("POST", moderation_path, {"action": "takedown", "reason": "完成下架测试"})
        for subpath in ("", "/preview", "/download"):
            anon.request("GET", pub_path + subpath, status=404)
        self.assertEqual(self.bob.request("GET", "/favorites")["items"], [])

    def test_simulated_ai_job_is_owned_consumed_once_and_readable(self):
        admin = self.create_admin()
        capabilities = self.alice.request("GET", "/ai/capabilities")
        self.assertEqual((capabilities["available"], capabilities["provider"]), (True, "simulation"))
        self.assertEqual(self.alice.request("GET", "/ai/quota"), {"remaining": 0, "reserved": 0, "used": 0})
        grant = {"requestId": str(uuid4()), "count": 1}
        quota_path = f"/ai/admin/quota/{self.alice_user['id']}"
        self.bob.request("POST", quota_path, grant, 403)
        granted = admin.request("POST", quota_path, grant)
        self.assertEqual(admin.request("POST", quota_path, grant), granted)
        self.assertEqual(granted["remaining"], 1)
        asset = self.alice.request("POST", "/assets", status=201, multipart=(png("red"), "source"))["id"]
        command = {"assetId": asset, "requestId": str(uuid4()), "provider": "simulation",
                   "prompt": "几何合成图", "consent": True}
        self.bob.request("POST", "/ai/jobs", command, 404)
        self.alice.request("POST", "/ai/jobs", {**command, "provider": "bailian"}, 409)
        queued = self.alice.request("POST", "/ai/jobs", command, 201)
        self.assertEqual((queued["status"], queued["provider"]), ("queued", "simulation"))
        self.assertEqual(self.alice.request("POST", "/ai/jobs", command, 201)["id"], queued["id"])
        self.alice.request("POST", "/ai/jobs", {**command, "requestId": str(uuid4())}, 409)
        self.bob.request("POST", f"/ai/jobs/{queued['id']}/cancel", status=404)
        self.assertEqual(self.bob.request("GET", "/ai/jobs")["items"], [])
        next_tab = Client(self.origin)
        next_tab.login(self.username, self.password)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            current = next_tab.request("GET", "/ai/jobs")["items"][0]
            if current["status"] not in ("queued", "running"):
                break
            time.sleep(0.18)
        self.assertEqual((current["id"], current["status"]), (queued["id"], "succeeded"))
        self.assertIsNotNone(current["outputId"])
        self.assertEqual(next_tab.request("GET", "/ai/quota"), {"remaining": 0, "reserved": 0, "used": 1})
        output = next_tab.request("GET", f"/assets/{current['outputId']}/content")
        with Image.open(io.BytesIO(output)) as generated:
            self.assertEqual((generated.format, generated.size), ("PNG", (64, 64)))
        self.bob.request("GET", f"/assets/{current['outputId']}/content", status=404)
        self.assertEqual(next_tab.request("POST", "/ai/jobs", command, 201)["id"], queued["id"])
        self.assertEqual(len(next_tab.request("GET", "/ai/jobs")["items"]), 1)

    def test_extensions_stock_completion_and_remix_provenance(self):
        admin = self.create_admin()
        series = admin.request("POST", "/admin/palettes", {
            "brand": f"Extension {uuid4().hex[:8]}", "series": "Standard", "sizeMm": 5,
        }, 201)["id"]
        palette = admin.request("POST", f"/admin/palettes/{series}/versions", {
            "version": "v1", "source": "https://example.test/fixture", "licenseStatus": "internal",
            "csv": "code,hex\nW1,#FFFFFF\nR1,#FF0000\nB1,#0000FF\n",
        }, 201)
        admin.request("POST", f"/admin/palette-versions/{palette['id']}/publish")
        self.alice.request("POST", "/inventory/import", {"versionId": palette["id"], "requestId": uuid4().hex,
                                                         "csv": "code,quantity\nW1,1\nB1,3\n"}, 201)
        colors_path = f"/inventory/available-colors/{palette['id']}"
        self.assertEqual(self.bob.request("GET", colors_path)["colors"], [])
        self.assertEqual([(v["code"], v["quantity"]) for v in self.alice.request("GET", colors_path)["colors"]],
                         [("B1", 3), ("W1", 1)])
        asset = self.alice.request("POST", "/assets", status=201, multipart=(png("red"), "source"))["id"]
        private_marker = "PRIVATE PALETTE DESCRIPTION"
        pattern = {"width": 2, "height": 2, "cells": ["W1", "R1", "W1", None], "colorLimit": 2,
                   "palette": [{"code": "W1", "hex": "#FFFFFF"}, {"code": "R1", "hex": "#FF0000"}],
                   "paletteId": f"db:{palette['id']}", "paletteName": private_marker,
                   "paletteInfo": {"brand": private_marker, "series": "fixture", "version": "v1",
                                   "source": "https://example.test/private-fixture", "license": "fixture", "note": private_marker}}
        project = self.save_fixture(pattern, source_id=asset, project_fields={"locked": ["W1"]})
        project_path = f"/projects/{project['id']}"
        self.alice.request("GET", f"{project_path}/versions/1/substitutions/W1", status=409)
        candidates = self.alice.request("GET", f"{project_path}/versions/1/substitutions/R1")
        self.assertEqual(candidates["affectedCells"], 1)
        self.assertEqual({entry["code"] for entry in candidates["options"]}, {"W1", "B1"})
        self.bob.request("GET", f"{project_path}/versions/1/substitutions/R1", status=404)
        build = self.alice.request("POST", "/builds", {
            "projectId": project["id"], "versionId": project["version"]["id"], "blockSize": 16,
        }, 201)
        build_path = f"/builds/{build['id']}"
        record = {"minutes": 45, "note": "合成测试成品", "photoId": None}
        self.alice.request("PUT", f"{build_path}/completion", record, 409)
        self.alice.request("PATCH", f"{build_path}/blocks",
                           {"x": 0, "y": 0, "completed": True, "expectedRevision": 1})
        self.alice.request("PUT", f"{build_path}/completion", {**record, "photoId": asset}, 422)
        photo = self.alice.request("POST", "/assets", status=201, multipart=(png("green"), "finished"))["id"]
        self.alice.request("PUT", f"{build_path}/completion", {**record, "photoId": photo})
        saved = self.alice.request("GET", f"{build_path}/completion")["completion"]
        self.assertEqual({key: saved[key] for key in record}, {**record, "photoId": photo})
        self.bob.request("GET", f"{build_path}/completion", status=404)
        self.bob.request("GET", f"/assets/{photo}/content", status=404)
        pending = self.publish_fixture(admin, project, allow_remix=True, approve=False)
        pub_path = f"/publications/{pending['id']}"
        command = {"requestId": uuid4().hex}
        self.bob.request("POST", f"{pub_path}/remix", command, 404)
        admin.request("POST", f"/admin{pub_path}/moderate", {"action": "approve", "reason": "合成测试图纸"})
        self.assertEqual(self.bob.request("GET", f"{pub_path}/difficulty"),
                         {"beadCount": 3, "colorCount": 2, "isolatedCount": 1})
        copy = self.bob.request("POST", f"{pub_path}/remix", command, 201)
        self.assertEqual(self.bob.request("POST", f"{pub_path}/remix", command, 201)["id"], copy["id"])
        pasted = self.bob.request("GET", f"/projects/{copy['id']}")
        self.assertIsNone(pasted["source_id"])
        self.assertIsNone(pasted["mask_id"])
        self.assertEqual(pasted["project"]["pattern"]["cells"], pattern["cells"])
        self.assertNotIn(private_marker, json.dumps(pasted, ensure_ascii=False))
        self.assertNotIn("private-fixture", json.dumps(pasted, ensure_ascii=False))
        provenance = self.bob.request("GET", f"/projects/{copy['id']}/provenance")["origin"]
        self.assertEqual((provenance["publicationId"], provenance["title"]), (pending["id"], pending["title"]))
        self.alice.request("POST", f"{pub_path}/withdraw")
        self.bob.request("POST", f"{pub_path}/remix", {"requestId": uuid4().hex}, 404)

    def test_community_comments_notices_private_messages_and_blocks(self):
        admin = self.create_admin()
        project = self.save_fixture()
        publication = self.publish_fixture(admin, project, approve=False)
        pub_path = f"/publications/{publication['id']}"
        self.bob.request("POST", f"{pub_path}/comments", {"text": "验收评论"}, 404)
        admin.request("POST", f"/admin{pub_path}/moderate", {"action": "approve", "reason": "合成测试图纸"})
        comment = self.bob.request("POST", f"{pub_path}/comments", {"text": "验收评论"}, 201)
        self.alice.request("DELETE", f"/comments/{comment['id']}", status=404)
        self.assertEqual(self.alice.request("GET", f"{pub_path}/comments")["items"][0]["text"], "验收评论")
        notice = next(n for n in self.alice.request("GET", "/notifications")["items"] if n["kind"] == "comment")
        self.bob.request("PATCH", f"/notifications/{notice['id']}/read", status=404)
        self.assertTrue(self.alice.request("PATCH", f"/notifications/{notice['id']}/read")["read"])
        self.bob.request("DELETE", f"/comments/{comment['id']}", status=204)
        self.assertEqual(self.alice.request("GET", f"{pub_path}/comments")["items"], [])
        alice_id, bob_id = self.alice_user["id"], self.bob_user["id"]
        msg = {"requestId": uuid4().hex, "text": "隔离测试私信"}
        sent = self.bob.request("POST", f"/messages/{alice_id}", msg, 201)
        retry = self.bob.request("POST", f"/messages/{alice_id}", msg, 201)
        self.assertEqual({key: retry[key] for key in ("id", "text", "senderId")},
                         {key: sent[key] for key in ("id", "text", "senderId")})
        self.assertEqual([m["id"] for m in self.alice.request("GET", f"/messages/{bob_id}")["items"]], [sent["id"]])
        self.assertEqual(admin.request("GET", f"/messages/{bob_id}")["items"], [])
        self.assertEqual(admin.request("GET", "/conversations")["items"], [])
        self.alice.request("PUT", f"/blocks/{bob_id}", status=204)
        self.alice.request("PUT", f"/blocks/{bob_id}", status=204)
        denied_msg = {"requestId": uuid4().hex, "text": "屏蔽期私信"}
        self.bob.request("POST", f"/messages/{alice_id}", denied_msg, 403)
        self.alice.request("POST", f"/messages/{bob_id}", denied_msg, 403)
        self.alice.request("DELETE", f"/blocks/{bob_id}", status=204)
        self.bob.request("POST", f"/messages/{alice_id}", denied_msg, 201)
        self.assertEqual(len(self.alice.request("GET", f"/messages/{bob_id}")["items"]), 2)

    def test_simulated_shop_order_and_membership_owner_boundaries(self):
        admin = self.create_admin()
        anonymous = Client(self.origin)
        self.assertTrue(anonymous.request("GET", "/shop/status")["simulationEnabled"])
        anonymous.request("GET", "/shop/orders", status=401)
        self.bob.request("GET", "/admin/shop/orders", status=403)
        self.alice.request("POST", "/shop/orders", {"requestId": uuid4().hex, "totalCents": 1}, 400)
        plan = admin.request("POST", "/admin/shop/plans", {
            "title": f"测试套餐 {uuid4().hex[:8]}", "durationDays": 2,
            "priceCents": 1300, "benefits": ["合成验收权益"],
        }, 201)
        checkout = {"requestId": uuid4().hex, "planId": plan["id"]}
        order = self.alice.request("POST", "/shop/orders", checkout, 201)
        self.assertEqual(order["totalCents"], 1300)
        payment = f"/shop/orders/{order['id']}/simulate-payment"
        self.bob.request("POST", payment, {"scenario": "paid"}, 404)
        self.assertEqual(self.bob.request("GET", "/shop/orders")["items"], [])
        result = self.alice.request("POST", payment, {"scenario": "paid"})
        self.assertEqual(result["status"], "paid")
        self.assertEqual(self.alice.request("POST", payment, {"scenario": "paid"})["status"], "paid")
        self.assertEqual(self.bob.request("GET", "/shop/memberships")["items"], [])
        active = self.alice.request("GET", "/shop/memberships")["items"]
        self.assertEqual(len(active), 1)
        self.assertTrue(active[0]["active"])
        self.assertEqual(self.alice.request("GET", "/ai/quota"), {"remaining": 0, "reserved": 0, "used": 0})

    def test_collaboration_two_live_sockets_and_revision_isolation(self):
        from websockets.exceptions import ConnectionClosed, InvalidStatus
        from websockets.sync.client import connect

        asset = self.alice.request("POST", "/assets", status=201, multipart=(png("red"), "source"))["id"]
        project = self.save_fixture(source_id=asset)
        project_id = project["id"]
        project_path = f"/collab/projects/{project_id}"
        activated = self.alice.request("POST", f"{project_path}/room", status=201)
        path = f"/collab/rooms/{activated['id']}"
        room_url = self.origin.replace("http://", "ws://", 1) + f"/api/collab/ws/{activated['id']}"
        self.bob.request("GET", path, status=404)

        def socket_for(actor, origin=self.origin):
            return connect(room_url, origin=origin, additional_headers={"Cookie": actor.cookie_header()},
                           open_timeout=5, close_timeout=1, proxy=None)

        with self.assertRaises(InvalidStatus):
            socket_for(Client(self.origin))
        with self.assertRaises(InvalidStatus):
            socket_for(self.alice, "https://example.test")

        def invite(role):
            item = self.alice.request("POST", f"{project_path}/invite",
                                      {"username": self.bob_user["username"], "role": role}, 201)
            self.assertEqual(self.bob.request("POST", f"/collab/invitations/{item['id']}/accept")["role"], role)

        invite("viewer")
        edit = {"requestId": uuid4().hex, "changes": [{"index": 0, "code": "R1"}]}
        self.bob.request("POST", f"{path}/operations", edit, 403)
        with socket_for(self.bob) as view:
            snapshot = json.loads(view.recv(timeout=3))
            self.assertEqual((snapshot["type"], snapshot["room"]["role"]), ("snapshot", "viewer"))
            self.assertTrue({"source_id", "mask_id", "source", "mask"}.isdisjoint(snapshot["room"]))
            self.alice.request("DELETE", f"{project_path}/members/{self.bob_user['id']}", status=204)
            with self.assertRaises(ConnectionClosed) as disconnected:
                view.recv(timeout=3)
            self.assertEqual(disconnected.exception.rcvd.code, 4404)
        self.bob.request("GET", path, status=404)
        self.bob.request("GET", f"/assets/{asset}/content", status=404)
        invite("editor")

        def wait_for_operation(ws, sequence):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                event = json.loads(ws.recv(timeout=max(0.1, deadline - time.monotonic())))
                for row in event.get("operations", []):
                    if row["sequence"] == sequence:
                        return row
            raise AssertionError(f"WebSocket did not relay sequence {sequence}")

        with socket_for(self.alice) as first, socket_for(self.bob) as second:
            self.assertEqual(json.loads(first.recv(timeout=3))["room"]["sequence"], 0)
            self.assertEqual(json.loads(second.recv(timeout=3))["room"]["sequence"], 0)
            left = self.alice.request("POST", f"{path}/operations", edit, 201)
            self.assertEqual(wait_for_operation(second, 1), left)
            self.assertEqual(self.alice.request("POST", f"{path}/operations", edit, 201), left)
            right = self.bob.request("POST", f"{path}/operations", {
                "requestId": uuid4().hex, "changes": [{"index": 0, "code": None}],
            }, 201)
            self.assertEqual(wait_for_operation(first, 2), right)
            self.alice.request("POST", f"{path}/undo", {"operationId": left["id"], "requestId": uuid4().hex}, 409)
            undo = self.bob.request("POST", f"{path}/undo", {"operationId": right["id"], "requestId": uuid4().hex}, 201)
            self.assertEqual(wait_for_operation(first, 3), undo)
        subsequent = self.alice.request("POST", f"{path}/operations", {
            "requestId": uuid4().hex, "changes": [{"index": 1, "code": "W1"}],
        }, 201)
        with socket_for(self.bob) as reconnected:
            room = json.loads(reconnected.recv(timeout=3))["room"]
            self.assertEqual(room["sequence"], subsequent["sequence"])
            self.assertEqual(room["pattern"]["cells"], ["R1", "W1", "W1", None])
        self.bob.request("POST", f"{path}/commit", {"expectedSequence": 4}, 403)
        self.alice.request("POST", f"{path}/commit", {"expectedSequence": 3}, 409)
        committed = self.alice.request("POST", f"{path}/commit", {"expectedSequence": 4})
        self.assertEqual(committed["revision"], 2)
        restored = self.alice.request("GET", f"/projects/{project_id}")
        self.assertEqual(restored["project"]["pattern"]["cells"], room["pattern"]["cells"])
        self.assertEqual(restored["source_id"], asset)

    def test_local_recovery_one_use_and_private_export_close(self):
        admin = self.create_admin()
        anonymous = Client(self.origin)
        self.assertEqual(anonymous.request("GET", "/account/recovery/status"), {"mailEnabled": True})
        address = {"email": "synthetic-recipient@example.invalid", "password": self.password}
        self.alice.request("POST", "/account/recovery/address", {**address, "password": "invalid"}, 400)
        self.alice.request("POST", "/account/recovery/address", address, 202)
        # Read the local development fixture without outputting a one-use code.
        def read_code(subject):
            for path in self.outbox.glob("*.eml"):
                message = BytesParser(policy=email_policy).parsebytes(path.read_bytes())
                if message["Subject"] == subject and str(message["To"]) == address["email"]:
                    return message.get_body(preferencelist=("plain",)).get_content().strip().splitlines()[-1]
            self.fail("Development outbox did not contain the expected synthetic message")

        verify = {"code": read_code("豆影邮箱验证")}
        self.bob.request("POST", "/account/recovery/verify", verify, 400)
        self.alice.request("POST", "/account/recovery/verify", verify)
        self.alice.request("POST", "/account/recovery/verify", verify, 400)
        for username in (self.username, "unknown-mysql-fixture"):
            self.assertEqual(anonymous.request("POST", "/account/recovery/request", {"username": username}, 202),
                             {"accepted": True})
        new_password = secrets.token_urlsafe(20)
        reset = {"username": self.username, "password": new_password, "code": read_code("豆影密码重置")}
        anonymous.request("POST", "/account/recovery/reset", reset)
        anonymous.request("POST", "/account/recovery/reset", reset, 400)
        self.alice.request("GET", "/projects", status=401)
        self.alice.login(self.username, self.password, status=401)
        self.alice.login(self.username, new_password)
        asset = self.alice.request("POST", "/assets", status=201, multipart=(png("red"), "source"))["id"]
        project = self.save_fixture(source_id=asset)
        publication = self.publish_fixture(admin, project)
        archive_bytes = self.alice.request("GET", "/account/export")
        with ZipFile(io.BytesIO(archive_bytes)) as archive:
            manifest = json.loads(archive.read("projects.json"))
            self.assertEqual(manifest["account"]["id"], self.alice_user["id"])
            self.assertNotIn("password", json.dumps(manifest, ensure_ascii=False))
            self.assertEqual([p["id"] for p in manifest["projects"]], [project["id"]])
            self.assertEqual(archive.read(f"assets/{asset}.png"),
                             self.alice.request("GET", f"/assets/{asset}/content"))
        with ZipFile(io.BytesIO(self.bob.request("GET", "/account/export"))) as archive:
            self.assertEqual(archive.namelist(), ["projects.json"])
            self.assertEqual(json.loads(archive.read("projects.json"))["projects"], [])
        command = {"password": new_password, "acknowledge": True}
        self.alice.request("POST", "/account/close", {**command, "acknowledge": False}, 400)
        self.alice.request("POST", "/account/close", command, 204)
        self.alice.request("GET", "/account/export", status=401)
        self.alice.login(self.username, new_password, status=401)
        publication_path = f"/publications/{publication['id']}"
        for suffix in ("", "/preview", "/download"):
            anonymous.request("GET", publication_path + suffix, status=404)
        lookup = urlencode({"query": publication["title"]})
        self.assertEqual(anonymous.request("GET", f"/publications?{lookup}")["items"], [])
        # Self-closure is not an ordinary administrative freeze.
        admin.request("PATCH", f"/admin/users/{self.alice_user['id']}", {"status": "active", "reason": "恢复演练"}, 409)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        try:
            from platform_api.db import session_factory
            from platform_api.projects import Asset, Project
        finally:
            sys.path.pop(0)
        with session_factory()() as database:
            self.assertEqual(database.get(Project, project["id"]).owner_id, self.alice_user["id"])
            self.assertEqual(database.get(Asset, asset).owner_id, self.alice_user["id"])

    def test_structure_lease_expires_and_preserves_previous_room(self):
        saved = self.save_fixture()
        project = f"/projects/{saved['id']}"
        collaborative = "/collab" + project
        room = self.alice.request("POST", f"{collaborative}/room", status=201)
        path = f"/collab/rooms/{room['id']}"
        invitation = self.alice.request("POST", f"{collaborative}/invite", {
            "username": self.bob_user["username"], "role": "editor",
        }, 201)
        self.bob.request("POST", f"/collab/invitations/{invitation['id']}/accept")
        updated_pattern = {**saved["project"]["pattern"], "width": 3, "height": 1, "cells": ["R1", None, "W1"]}
        changes = {"name": "新版结构", "expected_revision": 1,
                   "project": {**saved["project"], "pattern": updated_pattern}}
        self.alice.request("PATCH", project, changes, 409)
        self.alice.request("POST", f"{project}/versions/{saved['version']['id']}/restore", {"expected_revision": 1}, 409)
        structure = f"{path}/structure"
        acquire = {"requestId": uuid4().hex, "expectedRevision": 1, "expectedSequence": 0}
        commit = {**changes, "leaseId": str(uuid4()), "expectedSequence": 0}
        self.alice.request("POST", f"{structure}/commit", commit, 409)
        self.bob.request("POST", f"{structure}/lease", acquire, 403)
        leased = self.alice.request("POST", f"{structure}/lease", acquire, 201)
        self.assertEqual(self.alice.request("POST", f"{structure}/lease", acquire, 201), leased)
        other_tab = Client(self.origin)
        other_tab.login(self.username, self.password)
        commit["leaseId"] = leased["leaseId"]
        other_tab.request("POST", f"{structure}/lease", {**acquire, "requestId": uuid4().hex}, 409)
        other_tab.request("POST", f"{structure}/commit", commit, 409)
        edit = {"requestId": uuid4().hex, "changes": [{"index": 0, "code": "R1"}]}
        self.bob.request("POST", f"{path}/operations", edit, 409)
        self.alice.request("POST", f"{path}/commit", {"expectedSequence": 0}, 409)

        # Set the synthetic lease just outside its lifetime without changing server time.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        try:
            from platform_api.auth import utc_now
            from platform_api.collab import StructureLease
            from platform_api.db import session_factory
        finally:
            sys.path.pop(0)
        with session_factory()() as database:
            owned = database.get(StructureLease, leased["leaseId"])
            self.assertEqual(owned.room_id, room["id"])
            owned.expires_at = utc_now() - timedelta(seconds=5)
            database.commit()
        self.alice.request("POST", f"{structure}/commit", commit, 409)
        self.assertEqual(self.bob.request("POST", f"{path}/operations", edit, 201)["sequence"], 1)
        current = self.alice.request("POST", f"{structure}/lease", {
            **acquire, "requestId": uuid4().hex, "expectedSequence": 1,
        }, 201)
        commit.update(leaseId=current["leaseId"], expectedSequence=1)
        receipt = self.alice.request("POST", f"{structure}/commit", commit)
        self.assertEqual(self.alice.request("POST", f"{structure}/commit", commit), receipt)
        self.assertEqual(receipt["revision"], 2)
        self.assertEqual(self.alice.request("GET", project)["project"]["pattern"], updated_pattern)
        prior_room = self.bob.request("GET", path)
        self.assertEqual((prior_room["status"], prior_room["pattern"]["width"]), ("committed", 2))
        self.assertEqual(prior_room["pattern"]["cells"], ["R1", "R1", "W1", None])

    def test_private_assets_idempotent_import_conflict_and_restore(self):
        image_a = png("red")
        asset = self.alice.request("POST", "/assets", status=201, multipart=(image_a, "source"))["id"]
        mask = self.alice.request("POST", "/assets", status=201, multipart=(png("black"), "mask"))["id"]
        self.alice.request("POST", "/assets", status=422, multipart=(b"not an image", "source"))
        self.alice.request("POST", "/assets", status=403, csrf=False, multipart=(image_a, "source"))
        downloaded = self.alice.request("GET", f"/assets/{asset}/content")
        with Image.open(io.BytesIO(downloaded)) as source:
            self.assertEqual(source.getpixel((32, 32)), (255, 0, 0, 255))
        self.bob.request("GET", f"/assets/{asset}/content", status=404)
        body = {
            "name": "测试版本",
            "source_id": asset,
            "mask_id": mask,
            "project": {"schemaVersion": 2, "pattern": {
                "width": 2, "height": 2, "cells": ["W1", None, "W1", "R1"],
                "palette": [{"code": "W1", "hex": "#FFFFFF"}, {"code": "R1", "hex": "#FF0000"}],
                "colorLimit": 2,
            }},
        }
        request_id = uuid4().hex
        command = {"request_id": request_id, **body}
        self.bob.request("POST", "/projects", command, 404)
        created = self.alice.request("POST", "/projects", command, 201)
        path = f"/projects/{created['id']}"
        retry = self.alice.request("POST", "/projects", command, 201)
        self.assertEqual(retry["id"], created["id"])
        self.assertEqual(retry["revision"], 1)
        self.assertEqual(self.alice.request("GET", "/projects")["total"], 1)
        self.assertEqual(self.bob.request("GET", "/projects")["total"], 0)
        self.bob.request("GET", path, status=404)
        self.bob.request("GET", f"{path}/versions", status=404)
        first = self.alice.request("GET", path)
        self.assertEqual(first["version"]["beadCount"], 3)
        self.assertEqual(first["version"]["colorCount"], 2)
        invalid = deepcopy(body)
        invalid["project"]["pattern"]["cells"][0] = "undefined"
        self.alice.request("PATCH", path, {"expected_revision": 1, **invalid}, 422)
        self.bob.request("PATCH", path, {"expected_revision": 1, **body}, 404)
        other_tab = Client(self.origin)
        other_tab.login(self.username, self.password)
        ready = threading.Barrier(2, timeout=5)

        def edit(tab, name):
            ready.wait()
            return tab.request("PATCH", path, {"expected_revision": 1, **body, "name": name}, None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            left = pool.submit(edit, self.alice, "左页")
            right = pool.submit(edit, other_tab, "右页")
            attempts = [left.result(), right.result()]
        self.assertEqual(sorted(status for status, _ in attempts), [200, 409])
        self.assertEqual([v["revision"] for v in self.alice.request("GET", f"{path}/versions")["items"]], [2, 1])
        restored = self.alice.request("POST", f"{path}/versions/{first['version']['id']}/restore",
                                      {"expected_revision": 2})
        self.assertEqual(restored["revision"], 3)
        self.assertEqual(self.alice.request("GET", path)["project"], first["project"])
        self.alice.request("POST", f"{path}/trash", {"expected_revision": 3})
        self.alice.request("GET", path, status=404)
        self.assertEqual(self.alice.request("GET", "/projects?trash=true")["total"], 1)
        self.alice.request("POST", f"{path}/untrash", {"expected_revision": 4})
        self.assertEqual(self.alice.request("GET", path)["revision"], 5)

    def test_session_revoke_and_cpu_segmentation_partition(self):
        anonymous = Client(self.origin)
        anonymous.request("GET", "/projects", status=401)
        participant_b = self.bob.request("GET", "/auth/me")["user"]["id"]
        uploaded_a = self.alice.request("POST", "/images", multipart=(png("red"), None))
        uploaded_b = self.bob.request("POST", "/images", multipart=(png("blue", (24, 24, 39, 39)), None))

        def segment_body(image):
            return {"imageId": image["imageId"], "box": [8, 8, 56, 56],
                    "points": [{"x": 32, "y": 32, "label": 1}], "revision": 2}

        self.bob.request("POST", "/segment", segment_body(uploaded_a), 404)
        self.alice.request("POST", "/segment", segment_body(uploaded_b), 404)
        observed_masks = []
        for actor, image, edge in [
            (self.alice, uploaded_a, 255), (self.bob, uploaded_b, 0), (self.alice, uploaded_a, 255),
        ]:
            result = actor.request("POST", "/segment", segment_body(image))
            self.assertEqual(result["imageId"], image["imageId"])
            prefix, encoded = result["mask"].split(",", 1)
            self.assertEqual(prefix, "data:image/png;base64")
            with Image.open(io.BytesIO(base64.b64decode(encoded))) as mask:
                self.assertEqual(mask.getpixel((32, 32)), 255)
                self.assertEqual(mask.getpixel((18, 18)), edge)
                observed_masks.append(mask.tobytes())
        self.assertEqual(observed_masks[0], observed_masks[2])
        stale = Client(self.origin)
        stale.login(self.username, self.password)
        new_password = secrets.token_urlsafe(20)
        changed = self.alice.request("POST", "/auth/password", {
            "currentPassword": self.password, "newPassword": new_password,
        })
        self.alice.csrf = changed["csrfToken"]
        stale.request("GET", "/projects", status=401)
        self.alice.request("POST", "/auth/logout", status=204)
        self.alice.request("GET", "/projects", status=401)
        self.assertEqual(self.bob.request("GET", "/auth/me")["user"]["id"], participant_b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
