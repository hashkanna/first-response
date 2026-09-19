from core.errors import safe_error_detail


def test_provider_error_redacts_process_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-api-value")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "test-only-modal-value")
    detail = safe_error_detail(RuntimeError("Failed test-only-api-value and test-only-modal-value"))
    assert "test-only" not in detail
    assert detail.count("[redacted]") == 2


def test_provider_error_redacts_url_and_bearer_credentials():
    detail = safe_error_detail(RuntimeError("https://example.test/call?key=test-query-value&retry=1 Bearer test-bearer-value"))
    assert "test-query-value" not in detail
    assert "test-bearer-value" not in detail
    assert "retry=1" in detail


def test_provider_error_is_bounded():
    assert len(safe_error_detail(RuntimeError("x" * 1000))) == 300
