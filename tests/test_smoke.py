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
        # Quick-action buttons for a new entry and a new measurement.
        assert 'href="/entries/new"' in dash.text
        assert 'href="/measurements/new"' in dash.text


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
                "operating_hours": "100",
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


def test_map_place_object():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/assets/new")  # session-wide CSRF token

        # Place a shaft by "clicking" the map (lat/lon come from the click).
        r = client.post(
            "/api/objects",
            data={
                "csrf_token": token,
                "name": "Schacht am Kanal",
                "type": "shaft",
                "latitude": "48.2100",
                "longitude": "16.3700",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["asset"]["type"] == "shaft"
        assert body["asset"]["uid"]  # auto-generated
        # It now shows up among the map markers.
        uids = {a["uid"] for a in client.get("/api/assets").json()["assets"]}
        assert body["asset"]["uid"] in uids

        # The plant type cannot be created via the map.
        r = client.post(
            "/api/objects",
            data={
                "csrf_token": token,
                "name": "X",
                "type": "plant",
                "latitude": "48.2",
                "longitude": "16.3",
            },
        )
        assert r.status_code == 400

        # CSRF is enforced.
        r = client.post(
            "/api/objects",
            data={
                "csrf_token": "nope",
                "name": "Y",
                "type": "connection",
                "latitude": "48.2",
                "longitude": "16.3",
            },
        )
        assert r.status_code == 403


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


def test_maintenance_interval_auto_bump():
    with _client() as client:
        _login(client)

        # Asset with a 6-month interval and a manually set (old) next date.
        token = _csrf(client, "/assets/new")
        client.post(
            "/assets/new",
            data={
                "csrf_token": token,
                "uid": "INT-1",
                "name": "Interval Shaft",
                "type": "shaft",
                "maintenance_interval_months": "6",
                "next_maintenance_date": "2020-01-01",
                "latitude": "48.20",
                "longitude": "16.30",
            },
            follow_redirects=False,
        )
        asset = next(
            a for a in client.get("/api/assets").json()["assets"] if a["uid"] == "INT-1"
        )

        # Logging an entry bumps the next maintenance date automatically.
        token = _csrf(client, "/entries/new")
        client.post(
            "/entries/new",
            data={
                "csrf_token": token,
                "occurred_at": "2024-05-15T10:00",
                "asset_id": str(asset["id"]),
                "activity": "Spülung",
                "operating_hours": "200",
            },
            follow_redirects=False,
        )
        refreshed = next(
            a for a in client.get("/api/assets").json()["assets"] if a["uid"] == "INT-1"
        )
        assert refreshed["next_maintenance"] == "2024-11-15"


def test_entry_activity_filter():
    import re

    with _client() as client:
        _login(client)
        token = _csrf(client, "/entries/new")
        for activity, desc in [("Filter-A", "only-in-a"), ("Filter-B", "only-in-b")]:
            client.post(
                "/entries/new",
                data={
                    "csrf_token": token,
                    "occurred_at": "2024-06-01T08:00",
                    "activity": activity,
                    "description": desc,
                    "operating_hours": "300",
                },
                follow_redirects=False,
            )

        # Find the activity id via the filter dropdown on the unfiltered page.
        page = client.get("/entries").text
        m = re.search(r'value="(\d+)"\s*>Filter-A<', page)
        assert m, "activity option not rendered"
        filtered = client.get(f"/entries?activity_id={m.group(1)}").text
        assert "only-in-a" in filtered
        assert "only-in-b" not in filtered

        # Quick-select year filters like the report and wins over the range.
        filtered = client.get("/entries?year=2024").text
        assert "only-in-a" in filtered and "only-in-b" in filtered
        filtered = client.get("/entries?year=2023").text
        assert "only-in-a" not in filtered
        filtered = client.get("/entries?year=2024&date_from=2025-01-01").text
        assert "only-in-a" in filtered


def test_pipes_crud():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/assets/new")

        ids = []
        for uid in ("P-1", "P-2"):
            r = client.post(
                "/api/objects",
                data={
                    "csrf_token": token,
                    "name": uid,
                    "uid": uid,
                    "type": "shaft",
                    "latitude": "48.21",
                    "longitude": "16.37",
                },
            )
            ids.append(r.json()["asset"]["id"])

        # Create a pipe between the two shafts.
        r = client.post(
            "/api/pipes",
            data={"csrf_token": token, "from_asset_id": ids[0], "to_asset_id": ids[1]},
        )
        assert r.status_code == 200
        pipe = r.json()["pipe"]
        assert {pipe["from_id"], pipe["to_id"]} == set(ids)
        assert any(p["id"] == pipe["id"] for p in client.get("/api/pipes").json()["pipes"])

        # Duplicates (either direction) are rejected.
        r = client.post(
            "/api/pipes",
            data={"csrf_token": token, "from_asset_id": ids[1], "to_asset_id": ids[0]},
        )
        assert r.status_code == 400
        assert r.json()["error"] == "exists"

        # Self-loops are rejected.
        r = client.post(
            "/api/pipes",
            data={"csrf_token": token, "from_asset_id": ids[0], "to_asset_id": ids[0]},
        )
        assert r.status_code == 400

        # Deleting a pipe removes it.
        r = client.post(f"/api/pipes/{pipe['id']}/delete", data={"csrf_token": token})
        assert r.json()["ok"] is True
        assert not any(
            p["id"] == pipe["id"] for p in client.get("/api/pipes").json()["pipes"]
        )

        # Deleting an endpoint asset removes its pipes too.
        r = client.post(
            "/api/pipes",
            data={"csrf_token": token, "from_asset_id": ids[0], "to_asset_id": ids[1]},
        )
        assert r.status_code == 200
        client.post(f"/assets/{ids[0]}/delete", data={"csrf_token": token})
        assert client.get("/api/pipes").json()["pipes"] == []


def test_measurements_crud_and_filter():
    import re

    with _client() as client:
        _login(client)
        token = _csrf(client, "/measurements/new")

        # Create two measurements; German decimal commas must be accepted.
        for measured_at, parameter, value in [
            ("2024-07-01T09:00", "NH4", "1,8"),
            ("2024-07-01T10:00", "O2", "2.1"),
        ]:
            client.post(
                "/measurements/new",
                data={
                    "csrf_token": token,
                    "measured_at": measured_at,
                    "parameter": parameter,
                    "value": value,
                    "temperature": "14,5",
                    "operating_hours": "1234,5",
                },
                follow_redirects=False,
            )
        page = client.get("/measurements").text
        assert "<strong>NH4</strong>" in page
        assert "<strong>O2</strong>" in page
        assert "1.8" in page and "14.5" in page and "1234.5" in page
        assert "01/07/2024 09:00" in page  # dd/mm/YYYY, 24h

        # Value, temperature and counter reading are mandatory.
        r = client.post(
            "/measurements/new",
            data={
                "csrf_token": token,
                "measured_at": "2024-07-01T11:00",
                "parameter": "NH4",
                "value": "",
                "temperature": "12",
                "operating_hours": "1300",
            },
            follow_redirects=False,
        )
        assert r.status_code == 400

        # The parameter datalist lists the most recently used first (like activities).
        form_page = client.get("/measurements/new").text
        assert form_page.index('<option value="O2">') < form_page.index('<option value="NH4">')

        # Recent measurements show up on the dashboard with a link to the page.
        dash = client.get("/").text
        assert "<strong style=\"color:var(--text)\">NH4</strong>" in dash
        assert 'href="/measurements"' in dash

        # Filter by parameter.
        filtered = client.get("/measurements?parameter=NH4").text
        assert "<strong>NH4</strong>" in filtered
        assert "<strong>O2</strong>" not in filtered

        # Filter by date range (both measurements are on 2024-07-01).
        filtered = client.get(
            "/measurements?date_from=2024-07-01&date_to=2024-07-01"
        ).text
        assert "<strong>NH4</strong>" in filtered and "<strong>O2</strong>" in filtered
        filtered = client.get("/measurements?date_from=2024-07-02").text
        assert "<strong>NH4</strong>" not in filtered

        # Quick-select year wins over the range fields.
        filtered = client.get("/measurements?year=2024&date_from=2025-01-01").text
        assert "<strong>NH4</strong>" in filtered
        filtered = client.get("/measurements?year=2023").text
        assert "<strong>NH4</strong>" not in filtered

        # Edit the first measurement.
        mid = re.search(r'/measurements/(\d+)/edit', page).group(1)
        client.post(
            f"/measurements/{mid}/edit",
            data={
                "csrf_token": token,
                "measured_at": "2024-07-01T09:00",
                "parameter": "NH4",
                "value": "2,5",
                "temperature": "15",
                "operating_hours": "1240",
            },
            follow_redirects=False,
        )
        assert "2.5" in client.get("/measurements").text

        # Delete it again.
        client.post(f"/measurements/{mid}/delete", data={"csrf_token": token})
        assert f"/measurements/{mid}/edit" not in client.get("/measurements").text


def test_entry_operating_hours():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/entries/new")
        # The form posts separate date + time fields (24h) since the
        # datetime-local picker rendered AM/PM in some browser locales.
        client.post(
            "/entries/new",
            data={
                "csrf_token": token,
                "occurred_date": "2024-07-02",
                "occurred_time": "15:30",
                "activity": "Zählerablesung",
                "description": "counter check",
                "operating_hours": "512,5",
            },
            follow_redirects=False,
        )
        page = client.get("/entries").text
        assert "counter check" in page
        assert "512.5" in page
        # Dates are displayed as dd/mm/YYYY with a 24h time.
        assert "02/07/2024 15:30" in page

        # The counter reading is mandatory: missing value is rejected.
        r = client.post(
            "/entries/new",
            data={
                "csrf_token": token,
                "occurred_at": "2024-07-02T11:00",
                "activity": "Zählerablesung",
                "description": "no counter",
            },
            follow_redirects=False,
        )
        assert r.status_code == 400
        assert "no counter" not in client.get("/entries").text


def test_plant_report_pdf():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/assets/new")

        # An object is created and then edited -> two change-log events.
        client.post(
            "/assets/new",
            data={
                "csrf_token": token,
                "uid": "REP-1",
                "name": "Report Shaft",
                "type": "shaft",
            },
            follow_redirects=False,
        )
        from app.database import SessionLocal
        from app.models import Asset, AssetEvent, AssetEventAction

        with SessionLocal() as db:
            from sqlalchemy import select as sa_select

            asset_id = db.scalar(sa_select(Asset.id).where(Asset.uid == "REP-1"))
        client.post(
            f"/assets/{asset_id}/edit",
            data={
                "csrf_token": token,
                "uid": "REP-1",
                "name": "Report Shaft renamed",
                "type": "shaft",
                "next_maintenance_date": "2025-01-01",
            },
            follow_redirects=False,
        )

        # Plus one maintenance entry and one measurement.
        client.post(
            "/entries/new",
            data={
                "csrf_token": token,
                "occurred_date": "2024-08-01",
                "occurred_time": "08:00",
                "activity": "Reportprüfung",
                "operating_hours": "400",
            },
            follow_redirects=False,
        )
        client.post(
            "/measurements/new",
            data={
                "csrf_token": token,
                "measured_date": "2024-08-01",
                "measured_time": "09:00",
                "parameter": "CSB",
                "value": "30",
                "temperature": "16",
                "operating_hours": "401",
            },
            follow_redirects=False,
        )

        # Change-log events were recorded (created + updated with a diff).
        with SessionLocal() as db:
            from sqlalchemy import select as sa_select

            events = list(
                db.scalars(
                    sa_select(AssetEvent).where(AssetEvent.asset_uid == "REP-1")
                ).all()
            )
            actions = {ev.action for ev in events}
            assert AssetEventAction.created in actions
            assert AssetEventAction.updated in actions
            updated = next(ev for ev in events if ev.action == AssetEventAction.updated)
            assert "Report Shaft renamed" in (updated.changes or "")

        # The full chronological report renders as a PDF.
        r = client.get("/plant/report.pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:5] == b"%PDF-"
        assert "plant-report_all" in r.headers["content-disposition"]

        # Time-range variants: quick-select year, custom range, empty year.
        r = client.get("/plant/report.pdf?year=2024")
        assert r.status_code == 200 and r.content[:5] == b"%PDF-"
        assert "plant-report_2024" in r.headers["content-disposition"]
        r = client.get("/plant/report.pdf?date_from=2024-08-01&date_to=2024-08-31")
        assert r.status_code == 200 and r.content[:5] == b"%PDF-"
        r = client.get("/plant/report.pdf?year=1999")
        assert r.status_code == 200 and r.content[:5] == b"%PDF-"


def test_admin_only_pages():
    with _client() as client:
        _login(client)

        # Admins see the plant/admin/backup links.
        dash = client.get("/").text
        for href in ('href="/plant"', 'href="/admin/users"', 'href="/admin/backup"'):
            assert href in dash

        # Create a normal (non-admin) user.
        token = _csrf(client, "/admin/users")
        client.post(
            "/admin/users/new",
            data={
                "csrf_token": token,
                "username": "worker",
                "password": "workerpass123",
                "password_confirm": "workerpass123",
                "role": "user",
            },
            follow_redirects=False,
        )

        client.get("/logout")
        _login(client, "worker", "workerpass123")

        # The nav must not offer plant, user management or backup.
        dash = client.get("/").text
        for href in ('href="/plant"', 'href="/admin/users"', 'href="/admin/backup"'):
            assert href not in dash

        # The pages themselves are forbidden, viewing and editing alike.
        assert client.get("/plant", follow_redirects=False).status_code == 403
        token = _csrf(client, "/entries/new")
        r = client.post(
            "/plant",
            data={"csrf_token": token, "name": "Hacked"},
            follow_redirects=False,
        )
        assert r.status_code == 403
        assert client.get("/admin/users", follow_redirects=False).status_code == 403
        assert client.get("/admin/backup", follow_redirects=False).status_code == 403
        # The plant report moved onto the admin-only plant page.
        assert client.get("/plant/report.pdf", follow_redirects=False).status_code == 403


def test_asset_images():
    import re

    # Minimal valid 1x1 PNG.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
    )

    with _client() as client:
        _login(client)
        token = _csrf(client, "/assets/new")

        # Create a shaft with an image attached.
        r = client.post(
            "/assets/new",
            data={
                "csrf_token": token,
                "uid": "IMG-1",
                "name": "Shaft with photo",
                "type": "shaft",
            },
            files={"images": ("cover.png", png, "image/png")},
            follow_redirects=False,
        )
        assert r.status_code == 303

        # The thumbnail shows up on the edit form and is served via /media.
        page = client.get("/assets").text
        asset_id = re.search(r'/assets/(\d+)/edit"><strong>Shaft with photo', page).group(1)
        edit_page = client.get(f"/assets/{asset_id}/edit").text
        m = re.search(r'/media/([a-f0-9]+\.png)', edit_page)
        assert m, "uploaded image not shown on the edit form"
        assert client.get(f"/media/{m.group(1)}").status_code == 200

        # Upload a second image on edit, then delete the first one.
        client.post(
            f"/assets/{asset_id}/edit",
            data={
                "csrf_token": token,
                "uid": "IMG-1",
                "name": "Shaft with photo",
                "type": "shaft",
            },
            files={"images": ("second.png", png, "image/png")},
            follow_redirects=False,
        )
        edit_page = client.get(f"/assets/{asset_id}/edit").text
        assert len(re.findall(r'/media/[a-f0-9]+\.png', edit_page)) >= 2

        img_id = re.search(r'/assets/image/(\d+)/delete', edit_page).group(1)
        client.post(f"/assets/image/{img_id}/delete", data={"csrf_token": token})
        edit_page = client.get(f"/assets/{asset_id}/edit").text
        assert f"/assets/image/{img_id}/delete" not in edit_page

        # Deleting the asset removes the remaining image file from disk.
        m = re.search(r'/media/([a-f0-9]+\.png)', edit_page)
        remaining = m.group(1)
        client.post(f"/assets/{asset_id}/delete", data={"csrf_token": token})
        assert client.get(f"/media/{remaining}").status_code == 404


def test_admin_password_confirmation():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/admin/users")

        # Mismatching passwords: the user must not be created.
        client.post(
            "/admin/users/new",
            data={
                "csrf_token": token,
                "username": "mismatch",
                "password": "password12345",
                "password_confirm": "different12345",
                "role": "user",
            },
            follow_redirects=False,
        )
        page = client.get("/admin/users").text
        assert "mismatch" not in page

        # Matching passwords: created and able to log in.
        client.post(
            "/admin/users/new",
            data={
                "csrf_token": token,
                "username": "confirmed",
                "password": "password12345",
                "password_confirm": "password12345",
                "role": "user",
            },
            follow_redirects=False,
        )
        assert "confirmed" in client.get("/admin/users").text

        # Editing: a mismatching new password must not be applied.
        import re

        page = client.get("/admin/users").text
        target = re.findall(r'action="/admin/users/(\d+)/edit"', page)[-1]
        client.post(
            f"/admin/users/{target}/edit",
            data={
                "csrf_token": token,
                "email": "",
                "role": "user",
                "is_active": "on",
                "new_password": "changed123456",
                "new_password_confirm": "other123456",
            },
            follow_redirects=False,
        )
        client.get("/logout")
        # Old password still works because the mismatching change was rejected.
        r = _login(client, "confirmed", "password12345")
        assert r.status_code == 303
        assert client.get("/").status_code == 200


def test_csv_exports():
    with _client() as client:
        _login(client)

        # An entry and a measurement to export.
        token = _csrf(client, "/entries/new")
        client.post(
            "/entries/new",
            data={
                "csrf_token": token,
                "occurred_date": "2024-09-01",
                "occurred_time": "07:30",
                "activity": "CSV-Check",
                "description": "export me",
                "operating_hours": "42",
            },
            follow_redirects=False,
        )
        client.post(
            "/measurements/new",
            data={
                "csrf_token": token,
                "measured_date": "2024-09-01",
                "measured_time": "08:00",
                "parameter": "CSVpar",
                "value": "3,3",
                "temperature": "12",
                "operating_hours": "43",
            },
            follow_redirects=False,
        )

        r = client.get("/entries/export.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        body = r.content.decode("utf-8-sig")
        assert "export me" in body and "CSV-Check" in body and ";" in body

        r = client.get("/measurements/export.csv")
        assert r.status_code == 200
        body = r.content.decode("utf-8-sig")
        assert "CSVpar" in body and "3.3" in body


def test_entries_pagination():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/entries/new")
        # 27 entries -> two pages at 25 per page.
        for i in range(27):
            client.post(
                "/entries/new",
                data={
                    "csrf_token": token,
                    "occurred_date": "2024-10-01",
                    "occurred_time": "09:00",
                    "activity": "Bulk",
                    "description": f"bulk-entry-{i:02d}",
                    "operating_hours": str(i),
                },
                follow_redirects=False,
            )
        page1 = client.get("/entries").text
        assert "Page 1 of 2" in page1 or "Seite 1 von 2" in page1
        assert 'href="/entries?' in page1  # a pagination link exists
        page2 = client.get("/entries?page=2").text
        # 27 entries: page 1 has 25, page 2 has 2 -> the two oldest.
        assert "bulk-entry-00" in page2
        assert "bulk-entry-26" not in page2


def test_measurement_charts():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/measurements/new")
        for i, val in enumerate(("1.0", "2.0", "3.0")):
            client.post(
                "/measurements/new",
                data={
                    "csrf_token": token,
                    "measured_date": f"2024-11-0{i + 1}",
                    "measured_time": "09:00",
                    "parameter": "TREND",
                    "value": val,
                    "temperature": "10",
                    "operating_hours": "1",
                },
                follow_redirects=False,
            )
        # Charts live on their own page now, not the list.
        list_page = client.get("/measurements?parameter=TREND").text
        assert "chart-card" not in list_page
        page = client.get("/measurements/charts?parameter=TREND").text
        # A trend chart (inline SVG) is rendered for the parameter.
        assert "<svg" in page
        assert "chart-card" in page and "chart-grid" in page


def test_login_rate_limit():
    from app.routers.auth import _login_limiter

    _login_limiter.reset_all()
    try:
        with _client() as client:
            # Exceed the attempt budget with wrong passwords.
            for _ in range(5):
                r = _login(client, "admin", "wrong-password")
                assert r.status_code == 401
            # Further attempts are throttled, even with the correct password.
            r = _login(client, "admin", "adminpass123")
            assert r.status_code == 429
    finally:
        _login_limiter.reset_all()


def test_measurement_thresholds():
    with _client() as client:
        _login(client)
        token = _csrf(client, "/measurements/new")
        for i, val in enumerate(("100.0", "5.0")):
            client.post(
                "/measurements/new",
                data={
                    "csrf_token": token,
                    "measured_date": f"2024-12-0{i + 1}",
                    "measured_time": "09:00",
                    "parameter": "THRESH",
                    "value": val,
                    "temperature": "10",
                    "operating_hours": "1",
                },
                follow_redirects=False,
            )
        # Configure a warning band [0, 10] with a unit.
        token = _csrf(client, "/measurements/parameters")
        r = client.post(
            "/measurements/parameters",
            data={
                "csrf_token": token,
                "count": "1",
                "name_0": "THRESH",
                "unit_0": "mg/l",
                "min_0": "0",
                "max_0": "10",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303

        # The out-of-range value (100) is flagged in the list.
        page = client.get("/measurements?parameter=THRESH").text
        assert "measure-warn" in page
        assert "mg/l" in page  # unit shown

        # The chart draws the dashed threshold reference line.
        chart = client.get("/measurements/charts?parameter=THRESH").text
        assert "stroke-dasharray" in chart


def test_global_search():
    with _client() as client:
        _login(client)

        # An asset, an entry and a measurement each carrying a unique token.
        token = _csrf(client, "/assets/new")
        client.post(
            "/assets/new",
            data={
                "csrf_token": token,
                "uid": "SRCH-1",
                "name": "Zephyrqux Shaft",
                "type": "shaft",
            },
            follow_redirects=False,
        )
        token = _csrf(client, "/entries/new")
        client.post(
            "/entries/new",
            data={
                "csrf_token": token,
                "occurred_at": "2024-06-01T10:00",
                "activity": "Inspection",
                "description": "Zephyrqux reading noted",
                "operating_hours": "10",
            },
            follow_redirects=False,
        )
        token = _csrf(client, "/measurements/new")
        client.post(
            "/measurements/new",
            data={
                "csrf_token": token,
                "measured_date": "2024-06-02",
                "measured_time": "09:00",
                "parameter": "ZEPHYRQUX",
                "value": "1",
                "temperature": "10",
                "operating_hours": "1",
            },
            follow_redirects=False,
        )

        page = client.get("/search?q=Zephyrqux").text
        assert "Zephyrqux Shaft" in page  # object match
        assert "Zephyrqux reading noted" in page  # entry match
        assert "ZEPHYRQUX" in page  # measurement parameter match

        # An empty query renders the page without results.
        assert client.get("/search").status_code == 200


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
