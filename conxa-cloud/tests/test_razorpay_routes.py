from __future__ import annotations

import hashlib
import hmac
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from razorpay.errors import BadRequestError


class _FakePlanApi:
    def __init__(self, plan_id: str = "plan_starter_test", create_error: Exception | None = None) -> None:
        self.plan_id = plan_id
        self.create_error = create_error
        self.created_payloads: list[dict] = []

    def create(self, payload: dict) -> dict[str, str]:
        self.created_payloads.append(payload)
        if self.create_error:
            raise self.create_error
        return {"id": self.plan_id}


class _FakeSubscriptionApi:
    def __init__(self, plan_id: str = "plan_starter_test") -> None:
        self.plan_id = plan_id
        self.created_payloads: list[dict] = []

    def create(self, payload: dict) -> dict[str, str]:
        self.created_payloads.append(payload)
        return {"id": "sub_starter_test"}

    def fetch(self, subscription_id: str) -> dict[str, str]:
        return {"id": subscription_id, "plan_id": self.plan_id}


class _FakeRazorpayClient:
    def __init__(self, plan_id: str = "plan_starter_test", plan_create_error: Exception | None = None) -> None:
        self.plan = _FakePlanApi(plan_id, plan_create_error)
        self.subscription = _FakeSubscriptionApi(plan_id)


class RazorpayRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        patcher = patch("conxa_core.config.settings.data_dir", self.tmp / "data")
        self.addCleanup(patcher.stop)
        patcher.start()
        auth_patcher = patch("conxa_core.config.settings.auth_required", False)
        self.addCleanup(auth_patcher.stop)
        auth_patcher.start()
        starter_plan_patcher = patch("conxa_core.config.settings.razorpay_starter_plan_id", "")
        self.addCleanup(starter_plan_patcher.stop)
        starter_plan_patcher.start()
        pro_plan_patcher = patch("conxa_core.config.settings.razorpay_pro_plan_id", "")
        self.addCleanup(pro_plan_patcher.stop)
        pro_plan_patcher.start()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _client(self) -> TestClient:
        from app.main import app

        return TestClient(app)

    def _admin_headers(self) -> dict[str, str]:
        return {
            "x-conxa-proxy-secret": "proxy-secret",
            "x-conxa-user-id": "user_admin",
            "x-conxa-org-id": "org_admin",
            "x-conxa-org-role": "org:admin",
        }

    def test_list_plans_returns_cost_model_inr_prices(self) -> None:
        client = self._client()

        res = client.get("/api/v1/subscriptions/plans")

        self.assertEqual(res.status_code, 200, res.text)
        plans = {plan["tier"]: plan for plan in res.json()["plans"]}
        self.assertEqual(plans["starter"]["amount"], 29999)
        self.assertEqual(plans["starter"]["currency"], "INR")
        self.assertEqual(plans["pro"]["amount"], 79999)
        self.assertEqual(plans["pro"]["currency"], "INR")

    def test_create_subscription_accepts_clerk_org_admin(self) -> None:
        client = self._client()
        fake_client = _FakeRazorpayClient()

        with (
            patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"),
            patch("app.api.razorpay_routes._client", return_value=fake_client),
        ):
            res = client.post(
                "/api/v1/subscriptions/create",
                json={"tier": "starter"},
                headers=self._admin_headers(),
            )

        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["subscription_id"], "sub_starter_test")
        self.assertEqual(body["plan_id"], "plan_starter_test")
        self.assertEqual(body["amount"], 2999900)
        self.assertEqual(body["currency"], "INR")
        self.assertEqual(body["tier"], "starter")
        self.assertEqual(fake_client.plan.created_payloads[0]["item"]["amount"], 2999900)
        self.assertEqual(fake_client.plan.created_payloads[0]["item"]["currency"], "INR")
        subscription_payload = fake_client.subscription.created_payloads[0]
        self.assertEqual(subscription_payload["plan_id"], "plan_starter_test")
        self.assertEqual(subscription_payload["total_count"], 1200)
        self.assertEqual(subscription_payload["quantity"], 1)
        self.assertEqual(subscription_payload["notes"]["workspace_id"], "org_admin")
        self.assertEqual(subscription_payload["notes"]["tier"], "starter")

    def test_configured_plan_id_bypasses_dynamic_plan_creation(self) -> None:
        client = self._client()
        fake_client = _FakeRazorpayClient()

        with (
            patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"),
            patch("conxa_core.config.settings.razorpay_starter_plan_id", "plan_starter_configured"),
            patch("app.api.razorpay_routes._client", return_value=fake_client),
        ):
            res = client.post(
                "/api/v1/subscriptions/create",
                json={"tier": "starter"},
                headers=self._admin_headers(),
            )

        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["plan_id"], "plan_starter_configured")
        self.assertEqual(body["tier"], "starter")
        self.assertEqual(fake_client.plan.created_payloads, [])
        subscription_payload = fake_client.subscription.created_payloads[0]
        self.assertEqual(subscription_payload["plan_id"], "plan_starter_configured")
        self.assertEqual(subscription_payload["total_count"], 1200)
        self.assertEqual(subscription_payload["quantity"], 1)
        self.assertEqual(subscription_payload["notes"]["workspace_id"], "org_admin")
        self.assertEqual(subscription_payload["notes"]["tier"], "starter")

    def test_create_subscription_surfaces_missing_razorpay_credentials(self) -> None:
        client = self._client()

        with (
            patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"),
            patch("conxa_core.config.settings.razorpay_key_id", ""),
            patch("conxa_core.config.settings.razorpay_key_secret", ""),
        ):
            res = client.post(
                "/api/v1/subscriptions/create",
                json={"tier": "starter"},
                headers=self._admin_headers(),
            )

        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.json()["detail"], "Razorpay credentials not configured")

    def test_create_subscription_formats_empty_razorpay_plan_error(self) -> None:
        client = self._client()
        fake_client = _FakeRazorpayClient(plan_create_error=BadRequestError())

        with (
            patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"),
            patch("app.api.razorpay_routes._client", return_value=fake_client),
        ):
            res = client.post(
                "/api/v1/subscriptions/create",
                json={"tier": "starter"},
                headers=self._admin_headers(),
            )

        self.assertEqual(res.status_code, 500)
        self.assertEqual(res.json()["detail"], "failed_to_create_plan: BadRequestError")

    def test_create_subscription_does_not_reuse_legacy_price_plan_key(self) -> None:
        from app.api import razorpay_routes

        client = self._client()
        fake_client = _FakeRazorpayClient()
        legacy_plan_id = "plan_legacy_starter_499"
        razorpay_routes._write_plan_store({"starter": legacy_plan_id})

        with (
            patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"),
            patch("app.api.razorpay_routes._client", return_value=fake_client),
        ):
            res = client.post(
                "/api/v1/subscriptions/create",
                json={"tier": "starter"},
                headers=self._admin_headers(),
            )

        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["plan_id"], "plan_starter_test")
        self.assertEqual(fake_client.plan.created_payloads[0]["item"]["amount"], 2999900)
        store = razorpay_routes._read_plan_store()
        self.assertEqual(store["starter"], legacy_plan_id)
        self.assertEqual(store["starter:INR:2999900"], "plan_starter_test")

    def test_verify_subscription_accepts_legacy_plan_key(self) -> None:
        from app.api import razorpay_routes

        client = self._client()
        legacy_plan_id = "plan_legacy_starter_499"
        razorpay_routes._write_plan_store({"starter": legacy_plan_id})
        message = "pay_legacy|sub_legacy"
        signature = hmac.new(b"razorpay-secret", message.encode(), hashlib.sha256).hexdigest()

        with (
            patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"),
            patch("conxa_core.config.settings.razorpay_key_secret", "razorpay-secret"),
            patch("app.api.razorpay_routes._client", return_value=_FakeRazorpayClient(legacy_plan_id)),
        ):
            res = client.post(
                "/api/v1/subscriptions/verify",
                json={
                    "razorpay_payment_id": "pay_legacy",
                    "razorpay_subscription_id": "sub_legacy",
                    "razorpay_signature": signature,
                },
                headers=self._admin_headers(),
            )

        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"success": True})

    def test_verify_subscription_accepts_configured_plan_id(self) -> None:
        client = self._client()
        message = "pay_configured|sub_configured"
        signature = hmac.new(b"razorpay-secret", message.encode(), hashlib.sha256).hexdigest()

        with (
            patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"),
            patch("conxa_core.config.settings.razorpay_key_secret", "razorpay-secret"),
            patch("conxa_core.config.settings.razorpay_starter_plan_id", "plan_starter_configured"),
            patch("app.api.razorpay_routes._client", return_value=_FakeRazorpayClient("plan_starter_configured")),
        ):
            res = client.post(
                "/api/v1/subscriptions/verify",
                json={
                    "razorpay_payment_id": "pay_configured",
                    "razorpay_subscription_id": "sub_configured",
                    "razorpay_signature": signature,
                },
                headers=self._admin_headers(),
            )

        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json(), {"success": True})

    def test_create_subscription_rejects_clerk_org_member(self) -> None:
        client = self._client()

        with patch("conxa_core.config.settings.api_proxy_shared_secret", "proxy-secret"):
            res = client.post(
                "/api/v1/subscriptions/create",
                json={"tier": "starter"},
                headers={
                    "x-conxa-proxy-secret": "proxy-secret",
                    "x-conxa-user-id": "user_member",
                    "x-conxa-org-id": "org_member",
                    "x-conxa-org-role": "org:member",
                },
            )

        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["detail"], "admin role required")


if __name__ == "__main__":
    unittest.main()
