from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class ProductRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        patcher = patch("conxa_core.config.settings.data_dir", self.tmp / "data")
        self.addCleanup(patcher.stop)
        patcher.start()
        auth_patcher = patch("conxa_core.config.settings.auth_required", False)
        self.addCleanup(auth_patcher.stop)
        auth_patcher.start()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _client(self) -> TestClient:
        from app.main import app

        return TestClient(app)

    def test_local_identity_and_dashboard(self) -> None:
        client = self._client()
        me = client.get("/api/v1/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["workspace"]["id"], "wrk_local")

        dashboard = client.get("/api/v1/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["workspace"]["slug"], "local")
        self.assertIn("stats", dashboard.json())

    def test_trusted_proxy_headers_define_active_org(self) -> None:
        client = self._client()
        with patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"):
            me = client.get(
                "/api/v1/me",
                headers={
                    "x-conxa-proxy-secret": "proxy-secret",
                    "x-conxa-user-id": "user_123",
                    "x-conxa-org-id": "org_123",
                    "x-conxa-org-role": "admin",
                    "x-conxa-org-name": "Kiran's Organization",
                },
            )

        self.assertEqual(me.status_code, 200)
        body = me.json()
        self.assertEqual(body["user"]["id"], "user_123")
        self.assertEqual(body["workspace"]["id"], "org_123")
        self.assertEqual(body["workspace"]["role"], "admin")

    def test_invalid_proxy_secret_cannot_spoof_org(self) -> None:
        client = self._client()
        with patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"):
            me = client.get(
                "/api/v1/me",
                headers={
                    "x-conxa-proxy-secret": "wrong-secret",
                    "x-conxa-user-id": "user_123",
                    "x-conxa-org-id": "org_123",
                },
            )

        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["workspace"]["id"], "wrk_local")

    def test_missing_proxy_secret_does_not_trust_proxy_headers(self) -> None:
        client = self._client()
        me = client.get(
            "/api/v1/me",
            headers={
                "x-conxa-user-id": "user_123",
                "x-conxa-org-id": "org_123",
            },
        )

        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["workspace"]["id"], "wrk_local")

    def test_billing_subscription_local_fallback(self) -> None:
        client = self._client()
        res = client.get("/api/v1/billing/subscription")
        self.assertEqual(res.status_code, 200)
        payload = res.json()["subscription"]
        self.assertEqual(payload["plan"], "development")
        self.assertFalse(payload["stripe_configured"])

    def test_patch_bundle_release_records_release_and_audit(self) -> None:
        bundle_root = self.tmp / "bundle" / "render"
        bundle_root.mkdir(parents=True)

        def fake_bundle_root_dir(bundle_slug: str) -> Path | None:
            return bundle_root if bundle_slug == "render" else None

        client = self._client()
        with patch("app.api.product_routes.bundle_root_dir", side_effect=fake_bundle_root_dir):
            res = client.patch(
                "/api/v1/packages/bundles/render/release",
                json={"state": "published", "version": "1.2.3", "release_notes": "Initial release"},
            )
            self.assertEqual(res.status_code, 200)
            release = res.json()["release"]
            self.assertEqual(release["state"], "published")
            self.assertEqual(release["version"], "1.2.3")

        audit = client.get("/api/v1/audit-events")
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.json()["audit_events"][0]["resource_id"], "render")


if __name__ == "__main__":
    unittest.main()
