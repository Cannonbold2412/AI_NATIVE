"""Integration test for real LLM endpoint (gated by SKILL_LLM_TEXT_ENDPOINT env var)."""

import os
import pytest

from app.config import settings
from app.llm.openapi_client import generate_selector_candidates


pytestmark = pytest.mark.skipif(
    not settings.llm_text_endpoint or not settings.llm_text_api_key,
    reason="SKILL_LLM_TEXT_ENDPOINT not configured"
)


def test_selector_generation_real_endpoint():
    """Test generating selector candidates against real LLM endpoint."""
    html = """
    <html>
    <body>
        <div id="main">
            <button type="submit" data-testid="submit-btn">Submit Form</button>
            <input type="text" placeholder="Enter name" />
        </div>
    </body>
    </html>
    """

    result = generate_selector_candidates(
        html=html,
        element_tag="button",
        element_text="Submit Form",
        element_attrs={"type": "submit", "data-testid": "submit-btn"},
        semantic_description="A form submission button",
        model=settings.llm_text_model,
    )

    assert result is not None, "LLM returned None (connection or timeout issue)"
    assert "candidates" in result, "Missing 'candidates' key in response"
    candidates = result["candidates"]
    assert isinstance(candidates, list), "Candidates should be a list"
    assert len(candidates) > 0, "Should return at least one valid selector candidate"

    first_candidate = candidates[0]
    assert isinstance(first_candidate, dict), "Candidate should be a dict"
    assert "selector" in first_candidate, "Candidate should have 'selector' key"
    assert first_candidate["selector"], "Selector should not be empty"
