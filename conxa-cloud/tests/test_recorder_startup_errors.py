from app.recorder.session import format_startup_error


def test_format_startup_error_for_missing_playwright_browser() -> None:
    exc = RuntimeError(
        "BrowserType.launch: Executable doesn't exist at "
        "C:\\Users\\Lenovo\\AppData\\Local\\ms-playwright\\chromium\\chrome.exe"
    )

    message = format_startup_error(exc)

    assert "Playwright browser binaries are missing." in message
    assert "playwright install chromium" in message


def test_format_startup_error_passthrough_for_other_failures() -> None:
    exc = RuntimeError("Permission denied")

    assert format_startup_error(exc) == "Permission denied"
