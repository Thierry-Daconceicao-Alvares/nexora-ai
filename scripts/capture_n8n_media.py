"""Screenshots of the n8n side for the README, from a running stack.

Start the stack and give n8n something to show first:

    docker compose up -d --build
    python scripts/e2e_n8n.py --digest-command \
        "docker compose exec -T -e N8N_RUNNERS_BROKER_PORT=5690 n8n n8n execute --id 9b7dfceefef156"
    python scripts/capture_n8n_media.py

Writes docs/images/n8n-intake.png (the email intake workflow),
n8n-executions.png (its runs), mailbox.png (the emails n8n sent, in Mailpit)
and email-reply.png (the answer to a request received by email).

n8n asks for an owner account on a fresh instance: the script creates a local
one with a random password, used only for this run.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
SIZE = {"width": 1440, "height": 900}
INTAKE_WORKFLOW = "77589816edc957"
EMAIL = "owner@nexora.example"


def owner_password(n8n: str, password: str | None) -> str:
    """Create the owner of a fresh n8n instance; returns its password. With
    `password`, the owner already exists (a second run on the same instance)."""
    if password:
        return password
    password = "Nx-" + secrets.token_urlsafe(12) + "9a"
    response = httpx.post(
        f"{n8n}/rest/owner/setup",
        json={"email": EMAIL, "firstName": "Demo", "lastName": "Owner", "password": password},
        timeout=30,
    )
    if response.status_code >= 400:
        raise SystemExit(
            "n8n already has an owner: start from a fresh n8n volume "
            "(docker compose down -v), or pass --password with the owner's password."
        )
    return password


def sign_in(page: Page, n8n: str, email: str, password: str) -> None:
    page.goto(f"{n8n}/signin")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/home/**", timeout=30_000)


def close_popups(page: Page) -> None:
    """The production checklist n8n opens on a new instance."""
    close = page.locator("[data-test-id=suggested-actions-close]")
    if close.count() and close.first.is_visible():
        close.first.click()
        page.wait_for_timeout(500)


def hide_banners(page: Page) -> None:
    page.add_style_tag(
        content="[data-test-id=banners], .el-notification, "
        "[data-test-id=ask-assistant-floating-button] {display:none !important}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--n8n", default="http://localhost:5678")
    parser.add_argument("--mailpit", default="http://localhost:8025")
    parser.add_argument("--chromium", help="path to a Chromium binary")
    parser.add_argument(
        "--email", default=EMAIL, help="the owner's email, when n8n already has one"
    )
    parser.add_argument("--password", help="the owner's password, when n8n already has one")
    args = parser.parse_args()
    password = owner_password(args.n8n, args.password)
    print("n8n owner:", args.email, "(password not shown)")
    with sync_playwright() as p:
        options = {"executable_path": args.chromium} if args.chromium else {}
        browser = p.chromium.launch(**options)
        page = browser.new_page(viewport=SIZE, device_scale_factor=1)
        page.set_default_timeout(30_000)

        sign_in(page, args.n8n, args.email, password)
        page.goto(f"{args.n8n}/workflow/{INTAKE_WORKFLOW}")
        page.locator(".vue-flow__node").first.wait_for()
        hide_banners(page)
        page.wait_for_timeout(1500)
        close_popups(page)
        page.keyboard.press("1")  # zoom to fit
        page.wait_for_timeout(1500)
        page.screenshot(path=IMAGES / "n8n-intake.png")

        page.goto(f"{args.n8n}/home/executions")
        page.get_by_text("Success").first.wait_for()
        hide_banners(page)
        page.wait_for_timeout(1000)
        table = page.locator("table").first.bounding_box()
        page.screenshot(
            path=IMAGES / "n8n-executions.png",
            clip={
                "x": table["x"] - 24,
                "y": table["y"] - 24,
                "width": table["width"] + 48,
                "height": min(table["height"], 520) + 48,
            },
        )

        page.goto(args.mailpit)
        page.get_by_text("[NEXORA]").first.wait_for()
        page.wait_for_timeout(800)
        page.screenshot(path=IMAGES / "mailbox.png")

        page.get_by_text("Received: ").first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=IMAGES / "email-reply.png")
        browser.close()
    print("Written: docs/images/n8n-intake.png, n8n-executions.png, mailbox.png, email-reply.png")


if __name__ == "__main__":
    main()
