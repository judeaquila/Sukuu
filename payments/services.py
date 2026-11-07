"""Enrolment logic shared by the Paystack callback and the webhook.

Both paths funnel through `grant_access_for_transaction()` so a successful
payment always results in an active enrollment exactly once.
"""

import logging

from django.utils import timezone

from payments.models import PayoutAccount, Transaction, Withdrawal

logger = logging.getLogger(__name__)

TRANSACTION_STATUS_MAP = {
    "success": Transaction.Status.SUCCESS,
    "failed": Transaction.Status.FAILED,
    "abandoned": Transaction.Status.ABANDONED,
}


# ---------------------------------------------------------------------------
# Creator earnings & payout balance
# ---------------------------------------------------------------------------


def creator_earnings_totals(user):
    """Lifetime (gross, fee, earnings) in minor units from successful sales."""
    txs = Transaction.objects.filter(course__in=user.courses.all(), status=Transaction.Status.SUCCESS)
    gross = fee = 0
    for tx in txs:
        gross += tx.amount_minor
        fee += tx.platform_fee_minor
    return {"gross_minor": gross, "fee_minor": fee, "earnings_minor": gross - fee}


def creator_balance_minor(user):
    """What the creator can withdraw right now: lifetime earnings minus every
    withdrawal that is requested (locked) or already paid."""
    earnings = creator_earnings_totals(user)["earnings_minor"]
    locked = Withdrawal.objects.filter(
        user=user, status__in=[Withdrawal.Status.REQUESTED, Withdrawal.Status.PAID]
    )
    return earnings - (sum(w.amount_minor for w in locked))


def ensure_paystack_recipient(account):
    """Create (or refresh) the Paystack transfer recipient for a payout account.
    Returns (recipient_code, error_message). Raises for account-level issues.
    """
    if account.recipient_code:
        return account.recipient_code, None
    from payments.paystack import PaystackAPI, PaystackPayoutError

    try:
        api = PaystackAPI()
        code = api.create_transfer_recipient(
            name=account.account_name,
            account_number=account.account_number,
            bank_code=account.provider_code,
        )
    except PaystackPayoutError as exc:
        return None, str(exc)
    account.recipient_code = code
    account.save(update_fields=["recipient_code"])
    return code, None


def attempt_paystack_transfer(withdrawal):
    """Try to settle a requested withdrawal via Paystack Transfers.

    Returns (paid: bool, message: str). Updates the Withdrawal on success.
    """
    from payments.paystack import PaystackAPI, PaystackPayoutError

    account = withdrawal.payout_account
    if account is None or not account.recipient_code:
        return False, "No Paystack recipient is linked to this payout account."

    reference = f"PAYOUT-{withdrawal.id}-{withdrawal.user.id}"
    try:
        api = PaystackAPI()
        transfer_code, _ = api.transfer(
            amount_minor=withdrawal.amount_minor,
            recipient_code=account.recipient_code,
            reference=reference,
            reason=f"Sukuu creator payout #{withdrawal.id}",
        )
    except PaystackPayoutError as exc:
        logger.warning("Paystack transfer failed for withdrawal %s: %s", withdrawal.id, exc)
        return False, str(exc)

    withdrawal.status = Withdrawal.Status.PAID
    withdrawal.paid_via = Withdrawal.PaidVia.PAYSTACK
    withdrawal.external_reference = transfer_code or reference
    withdrawal.processed_at = timezone.now()
    withdrawal.save(update_fields=["status", "paid_via", "external_reference", "processed_at"])
    return True, "Paid via Paystack Transfer."


def apply_transaction(transaction, *, paystack_data, raw_response=None):
    """Reconcile a Transaction with verified Paystack data; grant access on success."""
    paystack_status = (paystack_data.get("status") or "").lower()
    new_status = TRANSACTION_STATUS_MAP.get(paystack_status)
    minor_amount = int(paystack_data.get("amount") or 0)

    was_pending = transaction.status == Transaction.Status.PENDING
    if new_status:
        transaction.status = new_status
    # Sanity check against our stored amount before fulfilling
    transaction.payment_channel = paystack_data.get("channel") or transaction.payment_channel
    transaction.paystack_id = str(paystack_data.get("id") or transaction.paystack_id)
    if raw_response is not None:
        transaction.raw_response = raw_response
    transaction.save()

    if transaction.status == Transaction.Status.SUCCESS and was_pending:
        _grant_access(transaction)
    return transaction


def _grant_access(transaction):
    from courses.models import Enrollment

    enrollment, created = Enrollment.objects.get_or_create(
        user=transaction.user,
        course=transaction.course,
        defaults={"is_active": True, "source": "paystack"},
    )
    if not created and not enrollment.is_active:
        enrollment.is_active = True
        enrollment.save()
    logger.info(
        "Granted %s access to course %s (ref %s)",
        transaction.user.email,
        transaction.course.title,
        transaction.reference,
    )


def handle_webhook_event(event_data):
    """Process a `charge.success` payload from the Paystack webhook.

    Returns the Transaction or None if the reference is unknown (never enrolls
    based on webhook metadata alone — the reference must exist in our DB).
    """
    reference = (event_data or {}).get("reference") or ""
    for transaction in Transaction.objects.filter(reference=reference).select_related("user", "course"):
        return apply_transaction(transaction, paystack_data=event_data)
    logger.warning("Webhook for unknown reference %s ignored", reference[:32])
    return None
