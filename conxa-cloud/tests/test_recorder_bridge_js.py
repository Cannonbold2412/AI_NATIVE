from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Browser, Page, sync_playwright

import conxa_compile.recorder as _recorder

BRIDGE_JS = (Path(_recorder.__file__).parent / "bridge.js").read_text(encoding="utf-8")


def _existing_chromium_executable(playwright_chromium) -> str | None:
    default = Path(playwright_chromium.executable_path)
    if default.is_file():
        return str(default)

    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data) / "ms-playwright"
        candidates.extend(sorted(root.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True))

    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env_name)
        if not base:
            continue
        candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
        candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        executable_path = _existing_chromium_executable(p.chromium)
        if not executable_path:
            pytest.skip("Chromium unavailable for recorder bridge tests")
        try:
            browser = p.chromium.launch(headless=True, executable_path=executable_path)
        except Exception as exc:  # pragma: no cover - depends on local browser install
            pytest.skip(f"Chromium unavailable for recorder bridge tests: {exc}")
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture()
def page(browser: Browser) -> Iterator[Page]:
    page = browser.new_page()
    try:
        yield page
    finally:
        page.close()


def _install_bridge(page: Page, html: str, profile: dict | None = None, capture_hover: bool = True) -> None:
    page.set_content(html)
    capture_profile = {"input_debounce_ms": 20, "hover_dwell_ms": 35}
    if profile:
        capture_profile.update(profile)
    page.evaluate(
        """args => {
            window.__events = [];
            window.__SKILL_CAPTURE_PROFILE__ = args.profile;
            window.__SKILL_CAPTURE_OPTIONS__ = { capture_hover: args.capture_hover };
            window.__skillReport = (payload) => window.__events.push(payload);
        }""",
        {"profile": capture_profile, "capture_hover": capture_hover},
    )
    page.evaluate(BRIDGE_JS)


def _events(page: Page) -> list[dict]:
    return page.evaluate("() => window.__events")


def _type_events(page: Page) -> list[dict]:
    return [event for event in _events(page) if event["action"]["action"] == "type"]


def _action_events(page: Page, action: str) -> list[dict]:
    return [event for event in _events(page) if event["action"]["action"] == action]


def test_native_input_records_single_debounced_type(page: Page) -> None:
    _install_bridge(page, '<input id="email" name="email" aria-label="Email" />')

    page.click("#email")
    page.keyboard.type("person@example.com")
    page.wait_for_timeout(200)

    events = _type_events(page)
    assert len(events) == 1
    assert events[0]["action"]["value"] == "person@example.com"
    assert events[0]["target"]["tag"] == "input"
    assert events[0]["semantic"]["intent_hint"] == "provide_input"


def test_role_textbox_records_type(page: Page) -> None:
    _install_bridge(
        page,
        '<div id="company" role="textbox" contenteditable="true" aria-label="Company"></div>',
    )

    page.click("#company")
    page.keyboard.type("Acme")
    page.wait_for_timeout(80)

    events = _type_events(page)
    assert len(events) == 1
    assert events[0]["action"]["value"] == "Acme"
    assert events[0]["target"]["role"] == "textbox"


def test_contenteditable_records_type(page: Page) -> None:
    _install_bridge(page, '<div id="notes" contenteditable="true" aria-label="Notes"></div>')

    page.click("#notes")
    page.keyboard.type("Follow up")
    page.wait_for_timeout(80)

    events = _type_events(page)
    assert len(events) == 1
    assert events[0]["action"]["value"] == "Follow up"


def test_open_shadow_root_input_records_type_through_composed_path(page: Page) -> None:
    _install_bridge(
        page,
        """
        <shadow-field id="field"></shadow-field>
        <script>
          customElements.define('shadow-field', class extends HTMLElement {
            connectedCallback() {
              const root = this.attachShadow({ mode: 'open' });
              root.innerHTML = '<input id="inner" name="shadow_email" aria-label="Shadow email" />';
            }
          });
        </script>
        """,
    )

    page.locator("shadow-field input").fill("shadow@example.com")
    page.wait_for_timeout(80)

    events = _type_events(page)
    assert len(events) == 1
    assert events[0]["action"]["value"] == "shadow@example.com"
    assert events[0]["target"]["tag"] == "input"
    assert events[0]["target"]["name"] == "shadow_email"


def test_custom_drawer_role_button_records_click(page: Page) -> None:
    _install_bridge(
        page,
        '<aside role="dialog"><div id="create" role="button" aria-label="Create">Create</div></aside>',
    )

    page.click("#create")
    page.wait_for_timeout(30)

    events = _events(page)
    assert len(events) == 1
    assert events[0]["action"]["action"] == "click"
    assert events[0]["target"]["role"] == "button"
    assert events[0]["target"]["aria_label"] == "Create"


def test_sidebar_form_fields_and_focusable_button_are_recorded(page: Page) -> None:
    _install_bridge(
        page,
        """
        <button id="createContacts">Create contacts</button>
        <div id="menu" hidden>
          <button id="newContact">New</button>
        </div>
        <aside id="drawer" class="right-sidebar" hidden>
          <label>Name <input id="name" name="contact_name" /></label>
          <label>Email <input id="email" name="email" /></label>
          <div id="submitContact" class="primary-action" tabindex="0">Create</div>
        </aside>
        <div id="toast" hidden>Created contact</div>
        <script>
          document.getElementById('createContacts').addEventListener('click', () => {
            document.getElementById('menu').hidden = false;
          });
          document.getElementById('newContact').addEventListener('click', () => {
            document.getElementById('drawer').hidden = false;
          });
          document.getElementById('submitContact').addEventListener('click', () => {
            document.getElementById('toast').hidden = false;
          });
        </script>
        """,
    )

    page.click("#createContacts")
    page.wait_for_timeout(180)
    page.click("#newContact")
    page.wait_for_timeout(180)
    page.fill("#name", "Ada Lovelace")
    page.fill("#email", "ada@example.com")
    page.wait_for_timeout(80)
    page.click("#submitContact")
    page.wait_for_timeout(180)

    events = _events(page)
    actions = [
        (event["action"]["action"], event["target"]["id"], event["action"]["value"])
        for event in events
        if event["action"]["action"] != "hover"
    ]
    assert actions == [
        ("click", "createContacts", None),
        ("click", "newContact", None),
        ("type", "name", "Ada Lovelace"),
        ("type", "email", "ada@example.com"),
        ("click", "submitContact", None),
    ]


def test_generic_text_click_without_ui_change_is_not_recorded(page: Page) -> None:
    _install_bridge(page, '<div id="plain">Plain text</div>')

    page.click("#plain")
    page.wait_for_timeout(180)

    assert _events(page) == []


def test_iframe_sidebar_form_records_when_bridge_runs_as_init_script(browser: Browser) -> None:
    context = browser.new_context()
    init_script = (
        "window.__SKILL_CAPTURE_PROFILE__ = { input_debounce_ms: 20, hover_dwell_ms: 35 };"
        "window.__skillReport = payload => {"
        "  window.top.__events = window.top.__events || [];"
        "  window.top.__events.push(payload);"
        "};\n"
        + BRIDGE_JS
    )
    context.add_init_script(init_script)
    page = context.new_page()
    try:
        page.set_content(
            """
            <script>window.__events = [];</script>
            <iframe
              id="object-builder-ui"
              data-test-id="object-builder-ui-iframe"
              data-selenium-test="associate-panel-iframe"
              data-iframe-ready="true"
              width="600"
              srcdoc='
              <label>First name <input id="firstName" name="firstname" /></label>
              <button id="create">Create</button>
            '></iframe>
            """
        )

        sidebar = page.frame_locator("#object-builder-ui")
        sidebar.locator("#firstName").fill("Ada")
        page.wait_for_timeout(80)
        sidebar.locator("#create").click()
        page.wait_for_timeout(80)

        actions = page.evaluate(
            "() => window.__events.map(event => [event.action.action, event.target.id, event.action.value])"
        )
        assert actions == [
            ["type", "firstName", "Ada"],
            ["click", "create", None],
        ]
    finally:
        context.close()


def test_focusable_button_click_records_without_immediate_ui_change(page: Page) -> None:
    _install_bridge(page, '<div id="submitContact" class="primary-action" tabindex="0">Create</div>')

    page.click("#submitContact")
    page.wait_for_timeout(40)

    events = _events(page)
    assert len(events) == 1
    assert events[0]["action"]["action"] == "click"
    assert events[0]["target"]["id"] == "submitContact"


def test_password_input_redacts_value(page: Page) -> None:
    _install_bridge(page, '<input id="password" type="password" name="password" />')

    page.fill("#password", "super-secret")
    page.wait_for_timeout(80)

    events = _type_events(page)
    assert len(events) == 1
    assert events[0]["action"]["value"] == "{{REDACTED}}"
    assert "super-secret" not in str(events[0])


def test_focusout_fallback_records_changed_value_without_input_event(page: Page) -> None:
    _install_bridge(page, '<input id="name" name="name" /><button id="next">Next</button>')

    page.click("#name")
    page.eval_on_selector("#name", "el => { el.value = 'Programmatic change'; }")
    page.click("#next")
    page.wait_for_timeout(80)

    events = _type_events(page)
    assert len(events) == 1
    assert events[0]["action"]["value"] == "Programmatic change"


def test_hover_reveals_menu_records_hover(page: Page) -> None:
    _install_bridge(
        page,
        """
        <nav>
          <div id="crm" role="menuitem" tabindex="0">CRM</div>
        </nav>
        <aside id="drawer" hidden>
          <a href="/contacts" id="contacts">Contacts</a>
        </aside>
        <script>
          document.getElementById('crm').addEventListener('mouseover', () => {
            document.getElementById('drawer').hidden = false;
          });
        </script>
        """,
    )

    page.hover("#crm")
    page.wait_for_timeout(120)

    events = _action_events(page, "hover")
    assert len(events) == 1
    assert events[0]["target"]["id"] == "crm"


def test_hover_capture_disabled_does_not_record_hover(page: Page) -> None:
    _install_bridge(
        page,
        """
        <nav>
          <div id="crm" role="menuitem" tabindex="0">CRM</div>
        </nav>
        <aside id="drawer" hidden>
          <a href="/contacts" id="contacts">Contacts</a>
        </aside>
        <script>
          document.getElementById('crm').addEventListener('mouseover', () => {
            document.getElementById('drawer').hidden = false;
          });
        </script>
        """,
        capture_hover=False,
    )

    page.hover("#crm")
    page.wait_for_timeout(120)

    assert _action_events(page, "hover") == []


def test_css_only_hover_style_change_records_nothing(page: Page) -> None:
    _install_bridge(
        page,
        """
        <style>
          #plain:hover { color: rgb(255, 0, 0); background: rgb(240, 240, 240); }
        </style>
        <button id="plain">Plain button</button>
        """,
    )

    page.hover("#plain")
    page.wait_for_timeout(120)

    assert _events(page) == []


def test_hover_target_that_collapses_before_emit_records_nothing(page: Page) -> None:
    _install_bridge(
        page,
        """
        <div id="loading" role="status" style="width: 80px; height: 24px;">Loading</div>
        <aside id="drawer" hidden>
          <button>Ready</button>
        </aside>
        <script>
          document.getElementById('loading').addEventListener('mouseover', () => {
            document.getElementById('loading').style.width = '0px';
            document.getElementById('loading').style.height = '0px';
            document.getElementById('drawer').hidden = false;
          });
        </script>
        """,
    )

    page.dispatch_event("#loading", "mouseover", {"bubbles": True})
    page.wait_for_timeout(120)

    assert _action_events(page, "hover") == []


def test_hover_then_click_revealed_child_records_hover_before_click(page: Page) -> None:
    _install_bridge(
        page,
        """
        <nav>
          <div id="crm" role="menuitem" tabindex="0">CRM</div>
        </nav>
        <aside id="drawer" hidden>
          <button id="contacts">Contacts</button>
        </aside>
        <script>
          document.getElementById('crm').addEventListener('mouseover', () => {
            document.getElementById('drawer').hidden = false;
          });
        </script>
        """,
        profile={"hover_dwell_ms": 1000},
    )

    page.hover("#crm")
    page.wait_for_timeout(80)
    page.click("#contacts")
    page.wait_for_timeout(80)

    actions = [event["action"]["action"] for event in _events(page)]
    assert actions[:2] == ["hover", "click"]
    assert _events(page)[0]["target"]["id"] == "crm"
    assert _events(page)[1]["target"]["id"] == "contacts"


def test_repeated_hover_over_unchanged_target_does_not_duplicate(page: Page) -> None:
    _install_bridge(
        page,
        """
        <nav>
          <div id="crm" role="menuitem" tabindex="0">CRM</div>
        </nav>
        <aside id="drawer" hidden>
          <button id="contacts">Contacts</button>
        </aside>
        <script>
          document.getElementById('crm').addEventListener('mouseover', () => {
            document.getElementById('drawer').hidden = false;
          });
        </script>
        """,
    )

    page.hover("#crm")
    page.wait_for_timeout(120)
    page.mouse.move(5, 5)
    page.wait_for_timeout(100)
    page.hover("#crm")
    page.wait_for_timeout(120)

    events = _action_events(page, "hover")
    assert len(events) == 1
