from __future__ import annotations

import json

from app.llm.router import LLMRouter, PoolEntry, _redacted_preview
from app.services.jobs import append_current_job_event, job_event_scope, job_store


def test_current_job_event_scope_appends_structured_events() -> None:
    job = job_store.create("test_compile_events")

    with job_event_scope(job.job_id):
        append_current_job_event("compile_phase", "Pipeline started.", {"phase": "pipeline_start", "count": 3})

    events = job_store.events_after(job.job_id, 0)
    assert any(
        event["event"] == "compile_phase"
        and event["message"] == "Pipeline started."
        and event["data"]["phase"] == "pipeline_start"
        for event in events
    )


def test_llm_preview_redacts_secrets_and_base64() -> None:
    preview = _redacted_preview(
        {
            "Authorization": "Bearer sk-live-secret",
            "image_base64": "A" * 120,
            "messages": [
                {
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + ("B" * 120)},
                        }
                    ]
                }
            ],
        }
    )

    assert "sk-live-secret" not in preview
    assert "A" * 80 not in preview
    assert "B" * 80 not in preview
    assert "[redacted]" in preview
    assert "[redacted_base64" in preview


def test_llm_router_emits_redacted_api_call_events(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"intent": "click_submit", "normalized_text": "submit", "confidence": 0.9}
                                )
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    monkeypatch.setattr("app.llm.router.request.urlopen", lambda *args, **kwargs: FakeResponse())

    job = job_store.create("test_llm_router_events")
    router = LLMRouter()
    entry = PoolEntry(
        provider="unit",
        endpoint="https://llm.example.test/v1?api_key=secret",
        api_key="sk-test-secret",
        text_model="unit-text",
        vision_model="unit-vision",
    )

    with job_event_scope(job.job_id):
        result = router._call_provider(
            entry,
            "semantic_enrichment",
            {"input": {"raw_text": "Submit"}, "Authorization": "Bearer sk-test-secret"},
            1000,
        )

    assert result == {"intent": "click_submit", "normalized_text": "submit", "confidence": 0.9}
    api_events = [event for event in job_store.events_after(job.job_id, 0) if event["event"] == "api_call"]
    assert [event["data"]["phase"] for event in api_events] == ["llm_request_start", "llm_request_done"]
    dumped = json.dumps(api_events)
    assert "sk-test-secret" not in dumped
    assert "api_key=secret" not in dumped
    assert "https://llm.example.test/v1/chat/completions?[redacted_query]" in dumped
