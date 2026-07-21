from dataclasses import dataclass
import json
import time
from typing import Any

import pyotp
from playwright.sync_api import Browser, BrowserContext, Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from fusi.config import AccountConfig


class USCISError(Exception):
    pass


class USCISChallengeError(USCISError):
    pass


class USCISLoginError(USCISError):
    pass


class USCISVerificationError(USCISError):
    pass


@dataclass(frozen=True)
class USCISCaseResult:
    receipt_number: str
    payload: dict[str, Any]

    @property
    def events(self) -> list[dict[str, Any]]:
        raw_events = self.payload['data'].get("events", [])
        return raw_events if isinstance(raw_events, list) else []


class USCISSession:
    def __init__(
        self,
        *,
        headless: bool = True,
        login_delay_ms: int = 1_000,
        sign_in_timeout_ms: int = 60_000,
        challenge_timeout_ms: int = 180_000,
    ) -> None:
        self.headless = headless
        self.login_delay_ms = login_delay_ms
        self.sign_in_timeout_ms = sign_in_timeout_ms
        self.challenge_timeout_ms = challenge_timeout_ms
        self._otp_attempted = False
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> "USCISSession":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.firefox.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def login(self, account: AccountConfig) -> None:
        page = self._require_page()
        self._pause_for_login_step(page)
        page.goto("https://myaccount.uscis.gov/sign-in", wait_until="domcontentloaded")
        self._pause_for_login_step(page)
        page.get_by_label("Email Address", exact=False).fill(account.email)
        self._pause_for_login_step(page)
        page.get_by_test_id("test-password").fill(account.password)

        with page.expect_response(
            lambda response: "/v1/authentication/sign_in" in response.url,
            timeout=self.sign_in_timeout_ms,
        ) as sign_in_info:
            self._pause_for_login_step(page)
            page.get_by_test_id("sign-in-btn").click()

        sign_in_response = sign_in_info.value
        if self._is_waf_challenge(sign_in_response):
            self._handle_waf_challenge(page)
        elif sign_in_response.status >= 400:
            raise USCISLoginError(self._extract_response_error(sign_in_response))

        self._wait_for_verification_page(page)

        payload = self._submit_verification_code(page, account)
        auth_state = payload.get("authentication_state")
        if auth_state == "incorrect_2fa_code_received":
            raise USCISVerificationError("USCIS rejected the TOTP code.")
        if isinstance(auth_state, str) and auth_state not in {"", "fully_signed_in"}:
            raise USCISVerificationError(
                f"Unexpected USCIS authentication state after TOTP verification: {auth_state}"
            )

    def fetch_case(self, receipt_number: str) -> USCISCaseResult:
        page = self._require_page()
        if not page.url.startswith("https://my.uscis.gov/"):
            self._open_case_app()

        result = page.evaluate(
            """
            async (receiptNumber) => {
                const response = await fetch(`/account/case-service/api/cases/${receiptNumber}`, {
                    credentials: 'include',
                    headers: { accept: 'application/json, text/plain, */*' },
                });
                const text = await response.text();
                return { status: response.status, url: response.url, text };
            }
            """,
            receipt_number,
        )

        if result["status"] >= 400:
            raise USCISError(
                f"USCIS case API returned HTTP {result['status']} for {receipt_number}."
            )

        try:
            payload = json.loads(result["text"])
        except json.JSONDecodeError as exc:
            raise USCISError(
                f"USCIS case API returned non-JSON content for {receipt_number}."
            ) from exc

        if not isinstance(payload, dict):
            raise USCISError(f"Unexpected USCIS case payload for {receipt_number}.")

        return USCISCaseResult(receipt_number=receipt_number, payload=payload)

    def _handle_waf_challenge(self, page: Page) -> None:
        try:
            self._wait_for_verification_page(page, timeout_ms=self.challenge_timeout_ms)
            return
        except USCISLoginError:
            if self.headless:
                raise USCISChallengeError(
                    "USCIS returned an AWS WAF challenge during sign-in. "
                    "Re-run with --headed and complete the captcha if it appears."
                ) from None
            raise USCISChallengeError(
                "USCIS sign-in is waiting on an AWS WAF challenge. "
                "Complete the captcha in the opened browser and try again."
            ) from None

    def _wait_for_verification_page(
        self,
        page: Page,
        *,
        timeout_ms: int | None = None,
    ) -> None:
        wait_timeout = timeout_ms or self.sign_in_timeout_ms
        try:
            page.get_by_role("heading", name="Verification Code").wait_for(
                timeout=wait_timeout
            )
        except PlaywrightTimeoutError as exc:
            message = self._extract_page_error(page) or "USCIS did not reach the TOTP step."
            raise USCISLoginError(message) from exc

    def _open_case_app(self) -> None:
        page = self._require_page()
        self._pause_for_login_step(page)
        page.goto("https://my.uscis.gov/account/applicant", wait_until="domcontentloaded")
        try:
            page.wait_for_url(
                "https://my.uscis.gov/account/applicant",
                timeout=self.sign_in_timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise USCISError(
                "USCIS login succeeded, but the case app did not open on my.uscis.gov."
            ) from exc

    def _submit_verification_code(
        self,
        page: Page,
        account: AccountConfig,
    ) -> dict[str, Any]:
        if self._otp_attempted:
            raise USCISVerificationError(
                "USCIS verification code was already submitted for this session."
            )

        self._otp_attempted = True
        with page.expect_response(
            lambda response: "/v1/authentication/verification_code" in response.url,
            timeout=self.sign_in_timeout_ms,
        ) as verification_info:
            self._pause_for_login_step(page)
            self._wait_for_fresh_totp_window(page)
            page.get_by_label("Secure Verification Code", exact=False).fill(
                pyotp.TOTP(account.totp_secret).now()
            )
            self._pause_for_login_step(page)
            page.get_by_test_id("2fa-submit-btn").click()

        verification_response = verification_info.value
        if verification_response.status >= 400:
            raise USCISVerificationError(self._extract_response_error(verification_response))

        return self._safe_json(verification_response)

    def _wait_for_fresh_totp_window(self, page: Page) -> None:
        interval_seconds = 30
        minimum_validity_seconds = 10
        remaining_seconds = interval_seconds - (time.time() % interval_seconds)
        if remaining_seconds < minimum_validity_seconds:
            wait_ms = int((remaining_seconds + 0.1) * 1_000)
            page.wait_for_timeout(wait_ms)

    def _extract_page_error(self, page: Page) -> str | None:
        alerts = page.locator("[role='alert'], [data-testid*='alert-message']")
        count = alerts.count()
        messages: list[str] = []
        for index in range(count):
            text = alerts.nth(index).inner_text().strip()
            if text:
                messages.append(text)
        return " ".join(messages) if messages else None

    def _extract_response_error(self, response: Response) -> str:
        payload = self._safe_json(response)
        for key in ("error", "msg", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        return f"USCIS returned HTTP {response.status} from {response.url}."

    def _safe_json(self, response: Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _is_waf_challenge(self, response: Response) -> bool:
        return response.status == 202 and response.header_value("x-amzn-waf-action") == "challenge"

    def _pause_for_login_step(self, page: Page) -> None:
        if self.login_delay_ms > 0:
            page.wait_for_timeout(self.login_delay_ms)

    def _require_page(self) -> Page:
        if self._page is None:
            raise USCISError("USCIS session has not been started.")
        return self._page
