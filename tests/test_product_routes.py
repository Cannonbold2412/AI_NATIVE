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
        patcher = patch("app.config.settings.data_dir", self.tmp / "data")
        self.addCleanup(patcher.stop)
        patcher.start()

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

    def test_billing_subscription_local_fallback(self) -> None:
        client = self._client()
        res = client.get("/api/v1/billing/subscription")
        self.assertEqual(res.status_code, 200)
        payload = res.json()["subscription"]
        self.assertEqual(payload["plan"], "development")
        self.assertFalse(payload["stripe_configured"])

    def test_publish_bundle_records_release_and_audit(self) -> None:
        bundle_root = self.tmp / "bundle" / "render"
        bundle_root.mkdir(parents=True)

        def fake_bundle_root_dir(bundle_slug: str) -> Path | None:
            return bundle_root if bundle_slug == "render" else None

        client = self._client()
        with patch("app.api.product_routes.bundle_root_dir", side_effect=fake_bundle_root_dir):
            res = client.post(
                "/api/v1/packages/bundles/render/publish",
                json={"version": "1.2.3", "release_notes": "Initial release"},
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
