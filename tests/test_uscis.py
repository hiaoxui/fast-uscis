import unittest
from unittest.mock import MagicMock, patch

from fusi.config import AccountConfig
from fusi.uscis import USCISCaseResult, USCISSession, USCISVerificationError


def build_account() -> AccountConfig:
    return AccountConfig(
        name="test",
        email="user@example.com",
        password="password",
        totp_secret="JBSWY3DPEHPK3PXP",
        receipts={},
    )


def build_page_with_response(*, status: int = 200, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.url = "https://myaccount.uscis.gov/v1/authentication/verification_code"
    response.json.return_value = payload or {"authentication_state": "fully_signed_in"}

    expectation = MagicMock()
    expectation.__enter__.return_value = expectation
    expectation.__exit__.return_value = False
    expectation.value = response

    page = MagicMock()
    page.expect_response.return_value = expectation
    return page


class USCISCaseResultTests(unittest.TestCase):
    def test_updated_at_comes_from_case_data(self) -> None:
        result = USCISCaseResult(
            receipt_number="IOE1",
            payload={
                "data": {
                    "updatedAt": "2026-06-24",
                    "events": [{"updatedAt": "2026-07-23"}],
                }
            },
        )

        self.assertEqual(result.updated_at, "2026-06-24")


class SubmitVerificationCodeTests(unittest.TestCase):
    @patch("fusi.uscis.time.time", return_value=15.0)
    @patch("fusi.uscis.pyotp.TOTP.now", return_value="123456")
    def test_allows_only_one_attempt(
        self,
        _: MagicMock,
        __: MagicMock,
    ) -> None:
        session = USCISSession()
        page = build_page_with_response()

        payload = session._submit_verification_code(page, build_account())

        self.assertEqual(payload["authentication_state"], "fully_signed_in")
        with self.assertRaisesRegex(USCISVerificationError, "already submitted"):
            session._submit_verification_code(page, build_account())

        self.assertEqual(page.expect_response.call_count, 1)
        self.assertEqual(page.wait_for_timeout.call_count, 2)
        page.wait_for_timeout.assert_any_call(session.login_delay_ms)
        page.get_by_label.return_value.fill.assert_called_once_with("123456")
        page.get_by_test_id.return_value.click.assert_called_once_with()

    @patch("fusi.uscis.time.time", return_value=29.0)
    @patch("fusi.uscis.pyotp.TOTP.now", return_value="123456")
    def test_waits_until_next_totp_window_near_expiration(
        self,
        _: MagicMock,
        __: MagicMock,
    ) -> None:
        session = USCISSession(login_delay_ms=0)
        page = build_page_with_response()

        session._submit_verification_code(page, build_account())

        page.wait_for_timeout.assert_called_once_with(1_100)
        page.get_by_label.return_value.fill.assert_called_once_with("123456")

    @patch("fusi.uscis.time.time", return_value=15.0)
    @patch("fusi.uscis.pyotp.TOTP.now", return_value="123456")
    def test_returns_rejected_otp_state_to_caller(
        self,
        _: MagicMock,
        __: MagicMock,
    ) -> None:
        session = USCISSession()
        page = build_page_with_response(
            payload={"authentication_state": "incorrect_2fa_code_received"}
        )

        payload = session._submit_verification_code(page, build_account())

        self.assertEqual(payload["authentication_state"], "incorrect_2fa_code_received")
        self.assertEqual(page.expect_response.call_count, 1)
        self.assertEqual(page.wait_for_timeout.call_count, 2)


class SessionLifecycleTests(unittest.TestCase):
    @patch("fusi.uscis.sync_playwright")
    def test_launches_firefox(self, sync_playwright: MagicMock) -> None:
        playwright = sync_playwright.return_value.start.return_value

        with USCISSession(headless=False):
            pass

        playwright.firefox.launch.assert_called_once_with(headless=False)
        playwright.chromium.launch.assert_not_called()
