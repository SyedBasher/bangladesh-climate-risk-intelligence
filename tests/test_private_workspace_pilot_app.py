import http.client
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

from clr.local_assets import import_asset_rows
from clr.local_store import (
    connect_catalog,
    finish_processing_run,
    initialize_workspace,
    register_source_file,
    start_processing_run,
    utc_now,
)
from clr.private_workspace_access import (
    apply_access_schema,
    create_user,
    grant_membership,
    verify_audit_chain,
)
from clr.private_workspace_pilot_app import (
    PILOT_SESSION_COOKIE,
    _csrf_for_token,
    make_pilot_handler,
    serve_private_pilot,
)


ROOT = Path(__file__).resolve().parents[1]


def _workspace(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(root, ROOT / "migrations" / "000_local_private_data_plane.sql")
    apply_access_schema(root, ROOT / "migrations" / "001_private_workspace_access.sql")
    import_asset_rows(
        root,
        [{
            "external_system": "SYNTH",
            "external_id": "A",
            "asset_type": "FACTORY",
            "latitude": 24.0,
            "longitude": 90.4,
            "coordinate_source": "SYNTHETIC",
            "site_identity_grade": "EXACT_SITE",
            "coordinate_status": "RESOLVED",
        }],
        tenant_key="TENANT_A",
    )
    source_file = root / "raw" / "era5_land" / "synthetic.bin"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"synthetic source")
    source = register_source_file(
        root,
        source_id="SYNTH_SOURCE",
        provider="SYNTHETIC",
        provider_version="v1",
        artifact_path=source_file,
        retrieved_at="2026-09-24T00:00:00+00:00",
    )
    with connect_catalog(root) as conn:
        asset = dict(
            conn.execute(
                "SELECT * FROM asset_location WHERE tenant_key='TENANT_A'"
            ).fetchone()
        )
    run_id = start_processing_run(
        root,
        pipeline_name="synthetic_indicator",
        pipeline_version="0.1",
        git_commit="syntheticsha",
        parameters={"tenant": "TENANT_A", "year": 2025},
    )
    with connect_catalog(root) as conn:
        cur = conn.execute(
            """
            INSERT INTO asset_indicator(
                tenant_key,asset_location_id,indicator_id,value_numeric,value_text,
                unit,value_class,measurement_basis,source_artifact_id,method_version,
                period_start,period_end,quality_flag,null_reason,run_id,calculated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "TENANT_A",
                asset["asset_location_id"],
                "flood_rp100_depth_m",
                0.5,
                None,
                "m",
                "SOURCE",
                "HYDROLOGICAL_HYDRODYNAMIC_MODEL",
                source["source_artifact_id"],
                "SYNTH",
                None,
                None,
                "OK",
                None,
                run_id,
                utc_now(),
            ),
        )
        conn.execute(
            """
            INSERT INTO asset_indicator_source(
                asset_indicator_id,source_artifact_id,source_role
            ) VALUES(?,?,?)
            """,
            (cur.lastrowid, source["source_artifact_id"], "PRIMARY"),
        )
        conn.commit()
    finish_processing_run(root, run_id, status="SUCCESS")

    users = {}
    for username, role in [
        ("viewer", "VIEWER"),
        ("analyst", "ANALYST"),
        ("admin", "ADMIN"),
    ]:
        user = create_user(
            root,
            username=username,
            password=f"synthetic-{username}-password",
            iterations=100_000,
        )
        grant_membership(
            root,
            user_id=user["user_id"],
            tenant_key="TENANT_A",
            role=role,
        )
        users[username] = user
    return root, asset, run_id, users


def _server(root, *, secure_cookie=False):
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_pilot_handler(
            root,
            session_minutes=30,
            secure_cookie=secure_cookie,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _login(conn, username, password):
    body = urlencode(
        {
            "username": username,
            "tenant": "TENANT_A",
            "password": password,
        }
    )
    conn.request(
        "POST",
        "/login",
        body=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body.encode("utf-8"))),
        },
    )
    response = conn.getresponse()
    response.read()
    assert response.status == 303
    cookie = response.getheader("Set-Cookie")
    assert cookie is not None
    return cookie


def _cookie_token(cookie):
    pair = cookie.split(";", 1)[0]
    name, value = pair.split("=", 1)
    assert name == PILOT_SESSION_COOKIE
    return pair, value


def test_named_user_login_and_secure_cookie_default(tmp_path):
    root, _, _, _ = _workspace(tmp_path)
    server, thread = _server(root, secure_cookie=True)
    host, port = server.server_address
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        cookie = _login(conn, "analyst", "synthetic-analyst-password")
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        assert "Secure" in cookie
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_viewer_can_view_dashboard_but_cannot_generate(tmp_path):
    root, asset, run_id, _ = _workspace(tmp_path)
    server, thread = _server(root)
    host, port = server.server_address
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        cookie = _login(conn, "viewer", "synthetic-viewer-password")
        cookie_pair, token = _cookie_token(cookie)

        conn.request("GET", "/", headers={"Cookie": cookie_pair})
        response = conn.getresponse()
        page = response.read().decode("utf-8")
        assert response.status == 200
        assert "VIEWER" in page
        assert "cannot generate new analytical reports" in page

        body = urlencode(
            {
                "csrf": _csrf_for_token(token),
                "scope": "ASSET",
                "asset_location_id": asset["asset_location_id"],
                "indicator_run": run_id,
            }
        )
        conn.request(
            "POST",
            "/generate",
            body=body,
            headers={
                "Cookie": cookie_pair,
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body.encode("utf-8"))),
            },
        )
        response = conn.getresponse()
        denied = response.read().decode("utf-8")
        assert response.status == 403
        assert "cannot generate reports" in denied

        with connect_catalog(root) as db:
            row = db.execute(
                """
                SELECT outcome FROM workspace_audit_event
                WHERE action='REPORT_GENERATE'
                ORDER BY audit_event_id DESC LIMIT 1
                """
            ).fetchone()
        assert row["outcome"] == "DENIED"
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_analyst_generates_private_report_and_audit_event(tmp_path):
    root, asset, run_id, _ = _workspace(tmp_path)
    server, thread = _server(root)
    host, port = server.server_address
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        cookie = _login(conn, "analyst", "synthetic-analyst-password")
        cookie_pair, token = _cookie_token(cookie)
        body = urlencode(
            {
                "csrf": _csrf_for_token(token),
                "scope": "ASSET",
                "asset_location_id": asset["asset_location_id"],
                "indicator_run": run_id,
                "flood_indicator_id": "flood_rp100_depth_m",
            },
            doseq=True,
        )
        conn.request(
            "POST",
            "/generate",
            body=body,
            headers={
                "Cookie": cookie_pair,
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body.encode("utf-8"))),
            },
        )
        response = conn.getresponse()
        response.read()
        assert response.status == 303
        assert response.getheader("Location").startswith("/report?path=")

        with connect_catalog(root) as db:
            row = db.execute(
                """
                SELECT outcome,target_type,target_id
                FROM workspace_audit_event
                WHERE action='REPORT_GENERATE'
                ORDER BY audit_event_id DESC LIMIT 1
                """
            ).fetchone()
        assert row["outcome"] == "SUCCESS"
        assert row["target_type"] == "ASSET"
        assert row["target_id"] == "SYNTH:A"
        assert verify_audit_chain(root)["valid"]
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_admin_can_view_tenant_audit_log(tmp_path):
    root, _, _, _ = _workspace(tmp_path)
    server, thread = _server(root)
    host, port = server.server_address
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        cookie = _login(conn, "admin", "synthetic-admin-password")
        cookie_pair, _ = _cookie_token(cookie)
        conn.request("GET", "/audit", headers={"Cookie": cookie_pair})
        response = conn.getresponse()
        page = response.read().decode("utf-8")
        assert response.status == 200
        assert "Tamper-evident chain status" in page
        assert "VALID" in page
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_pilot_backend_refuses_non_loopback_binding(tmp_path):
    root, _, _, _ = _workspace(tmp_path)
    try:
        serve_private_pilot(root, host="0.0.0.0", port=8766)
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("Expected non-loopback bind to fail")
