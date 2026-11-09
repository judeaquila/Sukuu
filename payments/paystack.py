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


# Kind strings used by paystack recipient creation
KIND_MOMO = "momo"
KIND_BANK = "bank"


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
        try:
            body = resp.json()
        except ValueError as exc:
            raise PaystackInitError(f"Unexpected non-JSON response from Paystack (HTTP {resp.status_code}).") from exc
        if not body.get("status") or resp.status_code != 200:
            raise PaystackInitError(body.get("message", f"HTTP {resp.status_code}"))
        return body

    def verify(self, reference):
        """GET transaction/verify/:reference → the full transaction object."""
        resp = self._get(f"/transaction/verify/{reference}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise PaystackVerificationError(f"Unexpected non-JSON response from Paystack (HTTP {resp.status_code}).") from exc
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

    def _response_json(self, resp):
        """Parse an API response body; non-JSON payloads (timeouts, HTML
        error pages from proxies, empty bodies) raise a friendly error."""
        try:
            return resp.json()
        except ValueError as exc:
            raise PaystackPayoutError(
                f"Unexpected non-JSON response from Paystack (HTTP {resp.status_code})."
            ) from exc

    def _get(self, path, params=None):
        try:
            resp = requests.get(
                f"{settings.PAYSTACK_API_BASE}{path}",
                headers=self._headers,
                params=params or {},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise PaystackPayoutError(f"Network error contacting Paystack: {exc}") from exc
        return resp

    def _post(self, path, payload):
        try:
            resp = requests.post(
                f"{settings.PAYSTACK_API_BASE}{path}",
                headers=self._headers,
                json=payload,
                timeout=60,
            )
        except requests.RequestException as exc:
            raise PaystackPayoutError(f"Network error contacting Paystack: {exc}") from exc
        return resp

    def list_banks(self, currency=None):
        """Bank + mobile-money provider lists for payout destinations.

        Returns {"banks": [{code, name}…], "momo": [{code, name}…]} for Ghana.
        Banks come from /bank?currency=GHS (type nuban) and MoMo providers from
        the type=mobile_money filter. Paystack can't send transfers to the Bank
        of Ghana, so it's excluded.
        """
        momo, banks = [], []
        for params, target in (
            ({"currency": currency or settings.CURRENCY, "type": "mobile_money"}, "momo"),
            ({"currency": currency or settings.CURRENCY}, "banks"),
        ):
            resp = self._get("/bank", params)
            body = self._response_json(resp)
            if not body.get("status"):
                raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
            entries = []
            for item in body.get("data") or []:
                code, name = item.get("code"), item.get("name")
                if not code or not name or "bank of ghana" in name.lower():
                    continue
                entries.append({"code": code, "name": name})
            if target == "momo":
                momo = entries
            else:
                banks = [
                    e for e in entries
                    if e not in momo  # dedupe against the MoMo list
                ]
        return {"banks": banks, "momo": momo}

    def create_transfer_recipient(self, *, name, account_number, bank_code, kind=None):
        """Create a transfer recipient on Paystack.

        kind: "momo" → type mobile_money; "bank" → type ghipss (Ghanaian bank).
        Returns (recipient_code, account_name) — account_name may be empty
        (Paystack only resolves it in some cases, e.g. sometimes for MoMo).
        """
        recipient_type = "mobile_money" if (kind or KIND_MOMO) == KIND_MOMO else "ghipss"
        payload = {
            "type": recipient_type,
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": settings.CURRENCY,
        }
        resp = self._post("/transferrecipient", payload)
        body = self._response_json(resp)
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        data = body.get("data") or {}
        recipient_code = data.get("recipient_code")
        if not recipient_code:
            raise PaystackPayoutError("Paystack did not return a recipient code.")
        account_name = (data.get("details") or {}).get("account_name") or ""
        return recipient_code, account_name

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
        resp = self._post("/transfer", payload)
        body = self._response_json(resp)
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        data = body.get("data") or {}
        return data.get("transfer_code"), data

    def delete_transfer_recipient(self, recipient_code):
        """Delete a transfer recipient (Paystack sets it inactive)."""
        try:
            resp = requests.delete(
                f"{settings.PAYSTACK_API_BASE}/transferrecipient/{recipient_code}",
                headers=self._headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise PaystackPayoutError(f"Network error contacting Paystack: {exc}") from exc
        body = self._response_json(resp)
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        return True

    def resolve_account_number(self, *, account_number, bank_code):
        """Verify a bank account number and return the resolved account name.

        Uses GET /bank/resolve (the documented endpoint). Note: Paystack's
        auto-resolution is mainly built for Nigerian NUBAN accounts — for other
        countries it may return an error, which callers must handle softly.
        """
        resp = self._get(
            "/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
        )
        body = self._response_json(resp)
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        return (body["data"] or {}).get("account_name") or ""

    def fetch_transfer(self, id_or_code):
        """Fetch the status details of a transfer (id or transfer_code)."""
        resp = self._get(f"/transfer/{id_or_code}")
        body = self._response_json(resp)
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        return body["data"]

    def finalize_transfer(self, *, transfer_code, otp):
        """Complete a transfer that Paystack held for OTP confirmation."""
        resp = self._post(
            "/transfer/finalize_destination",
            {"transfer_code": transfer_code, "otp": str(otp)},
        )
        body = self._response_json(resp)
        if not body.get("status"):
            raise PaystackPayoutError(body.get("message", f"HTTP {resp.status_code}"))
        return body["data"]
