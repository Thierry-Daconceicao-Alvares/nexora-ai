"""The interface end to end, in a real browser: a requester submits a request
through the form, the category buyer asks for information, the requester
completes it, the buyer approves it.

Runs the Streamlit app in demo mode (the API inside the app) on an empty
database. Needs Playwright and Chromium; skipped otherwise:

    pip install -e ".[ui,e2e]" && playwright install chromium
    pytest -m ui tests/ui
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.ui

ROOT = Path(__file__).resolve().parents[2]
CHROMIUM = os.environ.get("NEXORA_TEST_CHROMIUM")  # optional path to a Chromium binary


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    database = tmp_path_factory.mktemp("ui") / "ui.db"
    port = _free_port()
    env = {
        **os.environ,
        "NEXORA_DATABASE_URL": f"sqlite:///{database}",
        "NEXORA_LLM_PROVIDER": "scripted",
        "NEXORA_API_URL": "",
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app/streamlit_app.py",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    import httpx

    for _ in range(120):
        try:
            if httpx.get(f"{url}/_stcore/health", timeout=1).text == "ok":
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    else:
        process.kill()
        pytest.fail("The interface did not start.")
    yield url
    process.terminate()
    process.wait(timeout=20)


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        options = {"executable_path": CHROMIUM} if CHROMIUM else {}
        instance = p.chromium.launch(**options)
        yield instance
        instance.close()


def sign_in(page, name: str) -> None:
    page.get_by_role("combobox").first.click()
    page.get_by_role("option").filter(has_text=name).first.click()
    page.wait_for_timeout(1500)


def open_as(browser, url: str, name: str, path: str = ""):
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    page.set_default_timeout(30_000)
    page.goto(f"{url}/{path}")
    page.get_by_text("NEXORA AI").first.wait_for()
    sign_in(page, name)
    return page


def no_exception(page) -> None:
    assert page.locator("[data-testid=stException]").count() == 0


def test_submit_ask_complete_approve(app_url, browser):
    # Sophie submits a request through the form.
    page = open_as(browser, app_url, "Sophie Martin")
    page.get_by_role("link", name="New request").click()
    page.get_by_label("What do you need?").fill("Torque wrenches 20-100 Nm for cell 4")
    page.get_by_label("Why is it needed?").fill("Replacement of worn tools after the audit")
    page.get_by_label("Quantity").fill("6")
    page.get_by_label("Unit price").fill("385")
    page.get_by_role("button", name="Submit the request").click()
    page.get_by_text("Waiting for review").first.wait_for()
    request_id = re.search(r"request=([0-9a-f-]{36})", page.url).group(1)
    assert page.get_by_text("What the checks found").is_visible()
    no_exception(page)
    page.close()

    # Karim sees it in his queue and asks for a quote.
    page = open_as(browser, app_url, "Karim Benali")
    # The queue is a data grid drawn on a canvas: its cells are in the page, hidden.
    page.get_by_text("Torque wrenches 20-100 Nm for cell 4").first.wait_for(state="attached")
    page.goto(f"{app_url}/?request={request_id}")
    page.get_by_text("Your decision").wait_for()
    page.get_by_text("Ask the requester for information", exact=True).first.click()
    page.get_by_role("textbox", name="Reason (required)").fill("Please attach the written quote.")
    page.get_by_role("button", name="Send the question").click()
    page.get_by_text("Information requested").first.wait_for()
    no_exception(page)
    page.close()

    # Sophie completes it: version 2, checked again.
    page = open_as(browser, app_url, "Sophie Martin", f"?request={request_id}")
    page.get_by_text("Procurement needs more information").wait_for()
    page.get_by_label("Quote", exact=True).fill("1")
    page.get_by_role("button", name="Send the completed request").click()
    page.get_by_text("Version 2").wait_for()
    no_exception(page)
    page.close()

    # Karim approves; the decision stamp appears.
    page = open_as(browser, app_url, "Karim Benali", f"?request={request_id}")
    page.get_by_text("Your decision").wait_for()
    page.get_by_role("textbox", name="Reason (required)").fill(
        "Quote attached, tools within budget."
    )
    page.get_by_role("button", name="Approve the request").click()
    page.locator(".nx-stamp").get_by_text("Approved").wait_for()
    no_exception(page)
    page.close()


@pytest.mark.parametrize(
    ("person", "pages"),
    [
        ("Karim Benali", ["My queue", "Dashboard", "All requests"]),
        ("Claire Dubois", ["My queue", "Dashboard", "All requests"]),
        ("Sophie Martin", ["My requests", "New request", "Import a file"]),
        ("Demo administrator", ["Dashboard", "All requests", "Activity log"]),
    ],
)
def test_every_page_opens_for_every_role(app_url, browser, person, pages):
    page = open_as(browser, app_url, person)
    for name in pages:
        page.get_by_role("link", name=name).click()
        page.get_by_role("heading", name=name).first.wait_for()
        no_exception(page)
    page.close()
