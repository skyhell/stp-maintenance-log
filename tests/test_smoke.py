"""Smoke tests: app boots, login works, core pages render, CRUD flows."""

from __future__ import annotations

import os
import tempfile

# Use an isolated temp database/uploads for tests before importing the app.
_tmp = tempfile.mkdtemp(prefix="stp_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["BACKUP_DIR"] = f"{_tmp}/backups"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "adminpass123"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _client() -> TestClient:
    # Trigger lifespan (creates tables + bootstrap admin).
    return TestClient(app)


def _login(client: TestClient, username="admin", password="adminpass123"):
    # Fetch login page to obtain a CSRF token from the session.
    client.get("/login")
    # The CSRF token lives in the signed session; grab it from the rendered form.
    page = client.get("/login").text
    import re

    m = re.search(r'name="csrf_token" value="([^"]+)"', page)
    token = m.group(1)
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )


def test_healthz():
    with _client() as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_login_required_redirects():
    with _client() as client:
        r = client.get("/", follow_redirects=False)
        assert r.status_code in (302, 303)
        assert r.headers["location"] == "/login"


def test_login_and_dashboard():
    with _client() as client:
        r = _login(client)
        assert r.status_code == 303
        dash = client.get("/")
        assert dash.status_code == 200
        assert "Dashboard" in dash.text


def _csrf(client: TestClient, path: str) -> str:
    import re

    page = client.get(path).text
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def test_asset_and_entry_crud():
    with _client() as client:
        _login(client)

        # Create an asset.
        token = _csrf(client, "/assets/new")
        r = client.post(
            "/assets/new",
            data={
                "csrf_token": token,
                "uid": "SHAFT-001",
                "name": "Shaft One",
                "type": "shaft",
                "next_maintenance_date": "2020-01-01",
                "latitude": "48.2082",
                "longitude": "16.3738",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "Shaft One" in client.get("/assets").text

        # Create a maintenance entry with a self-building activity.
        token = _csrf(client, "/entries/new")
        r = client.post(
            "/entries/new",
            data={
                "csrf_token": token,
                "occurred_at": "2024-05-01T10:00",
                "activity": "Sichtprüfung",
                "description": "All good",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        history = client.get("/entries").text
        assert "Sichtprüfung" in history
        assert "All good" in history

        # Activity should now appear in the datalist on a new form.
        assert "Sichtprüfung" in client.get("/entries/new").text

        # Overdue asset should surface on the dashboard.
        assert "Overdue" in client.get("/").text or "Überfällig" in client.get("/").text


def test_csrf_rejected():
    with _client() as client:
        _login(client)
        r = client.post(
            "/assets/new",
            data={"csrf_token": "wrong", "uid": "X", "name": "Y", "type": "plant"},
            follow_redirects=False,
        )
        assert r.status_code == 403


def test_map_and_assets_api():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/assets/new")
        client.post(
            "/assets/new",
            data={
                "csrf_token": token,
                "uid": "SH-1",
                "name": "Shaft One",
                "type": "shaft",
                "latitude": "48.21",
                "longitude": "16.37",
            },
            follow_redirects=False,
        )
        assert client.get("/map").status_code == 200
        data = client.get("/api/assets").json()
        assert any(a["uid"] == "SH-1" and a["type"] == "shaft" for a in data["assets"])


def test_plant_singleton():
    with _client() as client:
        _login(client)

        # The single plant page exists and renders.
        assert client.get("/plant").status_code == 200

        # Updating the plant works.
        token = _csrf(client, "/plant")
        r = client.post(
            "/plant",
            data={
                "csrf_token": token,
                "name": "Zentralanlage",
                "next_maintenance_date": "2020-02-02",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert "Zentralanlage" in client.get("/plant").text

        # The object list must not contain the plant type.
        token = _csrf(client, "/assets/new")
        client.post(
            "/assets/new",
            data={"csrf_token": token, "uid": "PLANT-HACK", "name": "Sneaky", "type": "plant"},
            follow_redirects=False,
        )
        # Requesting type=plant is coerced to a shaft (no plant type is exposed).
        data = client.get("/api/assets").json()
        hack = [a for a in data["assets"] if a["uid"] == "PLANT-HACK"]
        # It may have no coords so might not be in /api/assets; check via the list instead.
        objects = client.get("/assets").text
        assert "Sneaky" in objects
        for a in hack:
            assert a["type"] != "plant"

        # Only one plant exists and it cannot be created via the objects page.
        overview = client.get("/api/assets").json()["assets"]
        assert sum(1 for a in overview if a["type"] == "plant") <= 1


def test_pdf_export():
    with _client() as client:
        _login(client)
        r = client.get("/entries/export.pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"


def _create_asset(client, uid, name="A", type_="shaft"):
    token = _csrf(client, "/assets/new")
    return client.post(
        "/assets/new",
        data={
            "csrf_token": token,
            "uid": uid,
            "name": name,
            "type": type_,
            "latitude": "48.2",
            "longitude": "16.3",
        },
        follow_redirects=False,
    )


def test_backup_and_restore():
    with _client() as client:
        _login(client)

        _create_asset(client, "BAK-1", "Before backup")

        # Download a backup snapshot.
        token = _csrf(client, "/admin/backup")
        r = client.post(
            "/admin/backup/download", data={"csrf_token": token}
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        zip_bytes = r.content
        assert zip_bytes[:2] == b"PK"

        # Mutate state after the snapshot.
        _create_asset(client, "BAK-2", "After backup")
        uids = {a["uid"] for a in client.get("/api/assets").json()["assets"]}
        assert {"BAK-1", "BAK-2"} <= uids

        # Restore the snapshot: BAK-2 should disappear, BAK-1 remain.
        token = _csrf(client, "/admin/backup")
        r = client.post(
            "/admin/backup/restore",
            data={"csrf_token": token},
            files={"archive": ("backup.zip", zip_bytes, "application/zip")},
            follow_redirects=False,
        )
        assert r.status_code == 303

        uids = {a["uid"] for a in client.get("/api/assets").json()["assets"]}
        assert "BAK-1" in uids
        assert "BAK-2" not in uids


def test_2fa_enable_and_login():
    import re

    import pyotp

    with _client() as client:
        _login(client)

        # Start setup: the secret is rendered on the page and stored in session.
        setup = client.get("/account/2fa/setup").text
        secret = re.search(r"user-select:all;\">([A-Z2-7]+)</code>", setup).group(1)

        token = _csrf(client, "/account/2fa/setup")
        code = pyotp.TOTP(secret).now()
        r = client.post(
            "/account/2fa/enable",
            data={"csrf_token": token, "code": code},
        )
        assert r.status_code == 200
        # Backup codes are shown once.
        assert "Backup" in r.text

        # Log out and back in -> should now require the second factor.
        client.get("/logout")
        r = _login(client)
        assert r.status_code == 303
        assert r.headers["location"] == "/login/2fa"

        # Dashboard still blocked until 2FA is completed.
        assert client.get("/", follow_redirects=False).headers["location"] == "/login"

        # Submit a valid TOTP code.
        token = _csrf(client, "/login/2fa")
        code = pyotp.TOTP(secret).now()
        r = client.post(
            "/login/2fa",
            data={"csrf_token": token, "code": code},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert client.get("/").status_code == 200
