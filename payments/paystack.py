import hmac
import hashlib
import json

import requests
from django.conf import settings


class PaystackInitError(Exception):
    """Failed to create a Paystack transaction."""


class PaystackVerificationError(Exception):
    """Failed to verify a transaction with Paystack."""


class PaystackPayoutError(Exception):
    """Failed to create a transfer recipient or transfer with Paystack."""


class PaystackAPI:
    """Thin wrapper over the Paystack REST API using the secret key from settings."""

    def __init__(self, secret_key=None):
        self.secret_key = secret_key or settings.PAYSTACK_SECRET_KEY

    @property
    def _headers(self):
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def initialize(self, *, email, amount_minor, reference, callback_url, metadata=None):
        """Create a hosted checkout and return the API response (with authorization_url)."""
        payload = {
            "email": email,
            "amount": amount_minor,  # minor units: pesewas for GHS, kobo for NGN
            "reference": reference,
            "callback_url": callback_url,
            "currency": settings.CURRENCY,
            "metadata": metadata or {},
        }
        try:
            resp = requests.post(
                f"{settings.PAYSTACK_API_BASE}/transaction/initialize",
                headers=self._headers,
                json=payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise PaystackInitError(f"Network error contacting Paystack: {exc}") from exc
        body = resp.json()
        if not body.get("status") or resp.status_code != 200:
            raise PaystackInitError(body.get("message", f"HTTP {resp.status_code}"))
        return body

    def verify(self, reference):
        """GET transaction/verify/:reference → the full transaction object."""
        try:
            resp = requests.get(
                f"{settings.PAYSTACK_API_BASE}/transaction/verify/{reference}",
                headers=self._headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise PaystackVerificationError(f"Network error contacting Paystack: {exc}") from exc
        body = resp.json()
        if not body.get("status"):
            raise PaystackVerificationError(body.get("message", f"HTTP {resp.status_code}"))
        return body["data"]

    def verify_webhook_signature(self, raw_body, signature):
        """Webhook verification per Paystack docs: HMAC SHA512 of the raw body with the secret key."""
        expected = hmac.new(self.secret_key.encode(), raw_body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    # ---------------------------------------------------------------
    # Payouts (Transfers)
    # ---------------------------------------------------------------

    def list_banks(self, currency=None):
        """Bank + mobile-money provider list for payout destinations.

        Returns a list of {"code": …, "name": …} dicts for banks (currency GHS)
        AND mobile money (type: mobile_money).
        """
        results = []
        for params in ({"currency": currency or settings.CURRENCY}, {"type": "mobile_money"}):
            try:
                resp = requests.get(
                    f"{settings.PAYSTACK_API_BASE}/bank",
                    headers=self._headers,
                    params=params,
                    timeout=30,
                )
            except requests.RequestException as exc:
                raise PaystackPayoutError(f"Network error contacting Paystack: {exc}") from exc
            body = resp.json()
            if not body.get("status"):
                raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
            results.extend(body.get("data") or [])
        return results

    def create_transfer_recipient(self, *, name, account_number, bank_code):
        """Create a transfer recipient on Paystack (MoMo or bank) and return its code."""
        payload = {
            "type": "mobile_money",
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": settings.CURRENCY,
        }
        try:
            resp = requests.post(
                f"{settings.PAYSTACK_API_BASE}/transferrecipient",
                headers=self._headers,
                json=payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise PaystackPayoutError(f"Network error contacting Paystack: {exc}") from exc
        body = resp.json()
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        recipient_code = (body.get("data") or {}).get("recipient_code")
        if not recipient_code:
            raise PaystackPayoutError("Paystack did not return a recipient code.")
        return recipient_code

    def transfer(self, *, amount_minor, recipient_code, reference=None, reason=None):
        """Send money to a transfer recipient. Returns (transfer_code|None, raw response)."""
        payload = {
            "source": "balance",
            "amount": amount_minor,
            "recipient": recipient_code,
            "reason": reason or "Creator payout",
        }
        if reference:
            payload["reference"] = reference
        try:
            resp = requests.post(
                f"{settings.PAYSTACK_API_BASE}/transfer",
                headers=self._headers,
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise PaystackPayoutError(f"Network error contacting Paystack: {exc}") from exc
        body = resp.json()
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        data = body.get("data") or {}
        return data.get("transfer_code"), data
