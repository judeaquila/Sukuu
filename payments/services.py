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
        user=user, status__in=[Withdrawal.Status.REQUESTED, Withdrawal.Status.PROCESSING, Withdrawal.Status.PAID]
    )
    return earnings - (sum(w.amount_minor for w in locked))


def resolve_coupon(course, code):
    """Validate a coupon code against a course.

    Returns (coupon, amount_minor) on success or (None, error_message) on
    failure. The final amount is always capped so at least GH₵1 is charged —
    Paystack can't process a GH₵0 charge.
    """
    from payments.models import Coupon
    from django.utils import timezone as _tz

    code = (code or "").strip().upper()
    if not code:
        return None, "Enter a coupon code."
    coupon = Coupon.objects.filter(code__iexact=code).first()
    if not coupon:
        return None, "That coupon code doesn't exist."
    if not coupon.is_active:
        return None, "That coupon is no longer active."
    if coupon.is_expired:
        return None, "That coupon has expired."
    if not coupon.has_redemptions_left:
        return None, "That coupon has been fully claimed."
    if not coupon.applies_to(course):
        return None, "That coupon doesn't apply to this course."
    if course.is_free:
        return None, "Coupons only apply to paid courses."
    final_minor = course.price_minor - coupon.discount_for(course)
    if final_minor < 100:
        return None, "This coupon's discount is too large for this course — choose a smaller discount."
    return coupon, final_minor


def payout_summary(user):
    """Available / pending / paid-out breakdown in minor units (creator dashboard)."""
    earnings = creator_earnings_totals(user)["earnings_minor"]
    pending = sum(
        w.amount_minor
        for w in Withdrawal.objects.filter(
            user=user,
            status__in=[Withdrawal.Status.REQUESTED, Withdrawal.Status.PROCESSING],
        )
    )
    paid = sum(
        w.amount_minor
        for w in Withdrawal.objects.filter(user=user, status=Withdrawal.Status.PAID)
    )
    return {
        "available_minor": earnings - pending - paid,
        "pending_minor": pending,
        "paidout_minor": paid,
    }


# ---------------------------------------------------------------------------
# Payout status emails
# ---------------------------------------------------------------------------

PAYOUT_EMAIL_TEMPLATES = {
    Withdrawal.Status.PROCESSING: (
        "Your payout of {amount} has been sent",
        "We've approved your payout request and initiated a Paystack transfer of "
        "{amount} to your {provider} account {masked}. "
        "It will appear as confirmed shortly — no action is needed on your part.",
    ),
    Withdrawal.Status.PAID: (
        "Payout complete — {amount} is on its way",
        "Great news! Your payout of {amount} to your {provider} account "
        "{masked} has been confirmed by Paystack and recorded in your payout history.",
    ),
    Withdrawal.Status.REJECTED: (
        "Your payout of {amount} was not completed",
        "Unfortunately your payout request of {amount} was not completed, and the "
        "funds have been returned to your LearnSasa balance.{note} You can request a "
        "new payout at any time from your Payouts page.",
    ),
}


def _payout_amount_text(withdrawal):
    from django.conf import settings

    symbol = getattr(settings, "CURRENCY_SYMBOL", "") or ""
    return f"{symbol}{withdrawal.amount_minor / 100:,.2f}"


def _masked_for_email(number):
    number = number or ""
    if len(number) > 6:
        return f"{number[:3]}••••{number[-3:]}"
    return number


def notify_withdrawal_status(withdrawal):
    """Email the creator whenever their payout changes state.

    Never raises — an email failure must not break payout settlement.
    """
    from django.conf import settings
    from django.core.mail import send_mail

    template = PAYOUT_EMAIL_TEMPLATES.get(withdrawal.status)
    if template is None or withdrawal.user is None:
        return

    subject_template, body_template = template
    note = ""
    if withdrawal.status == Withdrawal.Status.REJECTED and withdrawal.note:
        note = f"\n\nReason: {withdrawal.note}"
    amount = _payout_amount_text(withdrawal)
    subject = subject_template.format(amount=amount)
    body = body_template.format(
        amount=amount,
        provider=withdrawal.provider_name or withdrawal.get_kind_display(),
        masked=_masked_for_email(withdrawal.account_number) or "—",
        note=note,
    )
    try:
        send_mail(
            subject,
            (
                f"Hi {withdrawal.user.full_name or 'there'},\n\n"
                f"{body}\n\n— The LearnSasa team"
            ),
            settings.DEFAULT_FROM_EMAIL,
            [withdrawal.user.email],
            fail_silently=True,
        )
        logger.info(
            "Payout %s: status email sent to %s (%s)",
            withdrawal.id, withdrawal.user.email, withdrawal.status,
        )
    except Exception:
        logger.exception("Payout %s: status email failed", withdrawal.id)


def ensure_paystack_recipient(account):
    """Create (or refresh) the Paystack transfer recipient for a payout account.
    Returns (recipient_code, error_message). Raises for account-level issues.
    """
    if account.recipient_code:
        return account.recipient_code, None
    from payments.paystack import PaystackAPI, PaystackPayoutError

    try:
        api = PaystackAPI()
        code, resolved_name = api.create_transfer_recipient(
            name=account.account_name,
            account_number=account.account_number,
            bank_code=account.provider_code,
            kind=account.kind,
        )
    except PaystackPayoutError as exc:
        return None, str(exc)
    account.recipient_code = code
    fields = ["recipient_code"]
    if resolved_name and account.kind == PayoutAccount.Kind.MOMO and not account.verified_name:
        # Paystack resolved the registered name from the MoMo number
        account.verified_name = resolved_name
        fields.append("verified_name")
    account.save(update_fields=fields)
    return code, None


TRANSFER_STATUS_MAP = {
    "success": Withdrawal.Status.PAID,
    "failed": Withdrawal.Status.REJECTED,
    "reversed": Withdrawal.Status.REJECTED,
}


def settlement_outcome(paystack_transfer_status):
    """Map a Paystack transfer status to our Withdrawal status (or None to keep waiting)."""
    return TRANSFER_STATUS_MAP.get((paystack_transfer_status or "").lower())


def settle_with_transfer_status(withdrawal, paystack_status):
    """Apply one of the terminal statuses to a PROCESSING withdrawal.

    Success → PAID; failed/reversed (money returns to us) → REJECTED, which
    releases the creator's locked balance.
    """
    outcome = settlement_outcome(paystack_status)
    if withdrawal.status != Withdrawal.Status.PROCESSING or outcome is None:
        return withdrawal
    withdrawal.status = outcome
    if outcome == Withdrawal.Status.PAID:
        withdrawal.paid_via = Withdrawal.PaidVia.PAYSTACK
        withdrawal.processed_at = timezone.now()
    else:
        withdrawal.note = (withdrawal.note or "").strip() or f"Paystack reported: {paystack_status}"
        withdrawal.processed_at = timezone.now()
    withdrawal.save(update_fields=["status", "paid_via", "note", "processed_at", "external_reference"])
    notify_withdrawal_status(withdrawal)
    return withdrawal


def attempt_paystack_transfer(withdrawal):
    """Initiate the paystack transfer for a requested withdrawal.

    A withdrawal is only PAID once Paystack confirms the transfer succeeded —
    an initiated transfer puts it in PROCESSING until the webhook/requery.
    Returns (paid_or_processing: bool, message: str).
    """
    from payments.paystack import PaystackAPI, PaystackPayoutError

    account = withdrawal.payout_account
    if account is None or not account.recipient_code:
        return False, "No Paystack recipient is linked to this payout account."

    reference = f"PAYOUT-{withdrawal.id}-{withdrawal.user.id}"
    try:
        api = PaystackAPI()
        transfer_code, data = api.transfer(
            amount_minor=withdrawal.amount_minor,
            recipient_code=account.recipient_code,
            reference=reference,
            reason=f"LearnSasa creator payout #{withdrawal.id}",
        )
    except PaystackPayoutError as exc:
        logger.warning("Paystack transfer failed for withdrawal %s: %s", withdrawal.id, exc)
        return False, str(exc)

    withdrawal.external_reference = transfer_code or reference
    withdrawal.paid_via = Withdrawal.PaidVia.PAYSTACK
    status = settle_with_transfer_status(withdrawal, data.get("status") or "pending")
    if status.status not in {Withdrawal.Status.PAID, Withdrawal.Status.REJECTED}:
        # Non-terminal (otp/pending/processing): mark as PROCESSING
        withdrawal.status = Withdrawal.Status.PROCESSING
        withdrawal.save(update_fields=["status", "paid_via", "note", "processed_at", "external_reference"])
        notify_withdrawal_status(withdrawal)
        return True, (
            "Transfer initiated — awaiting confirmation"
            if (data.get("status") or "") != "otp"
            else "Transfer needs OTP confirmation (disable OTP in the Paystack dashboard or finalize it)."
        )
    return (
        withdrawal.status == Withdrawal.Status.PAID,
        "Paid via Paystack Transfer." if withdrawal.status == Withdrawal.Status.PAID
        else f"Transfer {data.get('status')}",
    )


def requery_processing_withdrawals():
    """Ask Paystack about every withdrawal currently PROCESSING and settle terminal ones."""
    from payments.paystack import PaystackAPI, PaystackPayoutError

    settled = []
    for withdrawal in Withdrawal.objects.filter(
        status=Withdrawal.Status.PROCESSING, paid_via=Withdrawal.PaidVia.PAYSTACK
    ).exclude(external_reference="").select_related("payout_account"):
        try:
            data = PaystackAPI().fetch_transfer(withdrawal.external_reference)
        except PaystackPayoutError as exc:
            logger.warning("Requery failed for withdrawal %s: %s", withdrawal.id, exc)
            continue
        before = withdrawal.status
        withdrawal = settle_with_transfer_status(withdrawal, (data or {}).get("status"))
        if withdrawal.status != before:
            settled.append((withdrawal.id, withdrawal.status))
    return settled


def apply_transaction(transaction, *, paystack_data, raw_response=None):
    """Reconcile a Transaction with verified Paystack data; grant access on success."""
    paystack_status = (paystack_data.get("status") or "").lower()
    new_status = TRANSACTION_STATUS_MAP.get(paystack_status)
    minor_amount = int(paystack_data.get("amount") or 0)

    # Sanity check against our stored amount before fulfilling
    if (
        minor_amount
        and transaction.amount_minor
        and minor_amount != transaction.amount_minor
    ):
        logger.warning(
            "Amount mismatch for ref %s: paid %s, expected %s",
            transaction.reference, minor_amount, transaction.amount_minor,
        )
        transaction.status = Transaction.Status.FAILED
        transaction.payment_channel = paystack_data.get("channel") or transaction.payment_channel
        transaction.paystack_id = str(paystack_data.get("id") or transaction.paystack_id)
        if raw_response is not None:
            transaction.raw_response = raw_response
        transaction.save()
        return transaction

    was_pending = transaction.status == Transaction.Status.PENDING
    if new_status:
        transaction.status = new_status
    transaction.payment_channel = paystack_data.get("channel") or transaction.payment_channel
    transaction.paystack_id = str(paystack_data.get("id") or transaction.paystack_id)
    if raw_response is not None:
        transaction.raw_response = raw_response
    transaction.save()

    if transaction.status == Transaction.Status.SUCCESS and was_pending:
        _grant_access(transaction)
        if transaction.coupon_id:
            # One redemption per confirmed purchase (webhook retries are guarded above)
            from payments.models import Coupon
            from django.db.models import F

            Coupon.objects.filter(pk=transaction.coupon_id).update(times_used=F("times_used") + 1)
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


def handle_webhook_event(event_name, event_data):
    """Process a webhook event payload we receive from Paystack.

    `charge.success` → fulfill a purchase transaction.
    `transfer.*` → settle creator payouts (success/failed/reversed).
    """
    event_data = event_data or {}
    if event_name == "charge.success":
        return _handle_charge_success(event_data)
    if event_name and event_name.startswith("transfer."):
        return _handle_transfer_event(event_name, event_data)
    logger.debug("Unhandled webhook event %s", event_name)
    return None


def _handle_charge_success(event_data):
    """Process a `charge.success`; returns Transaction or None."""
    reference = event_data.get("reference") or ""
    transaction = (
        Transaction.objects.filter(reference=reference)
        .select_related("user", "course")
        .first()
    )
    if not transaction:
        logger.warning("Webhook for unknown reference %s ignored", reference[:32])
        return None
    return apply_transaction(transaction, paystack_data=event_data)


def _handle_transfer_event(event_name, event_data):
    """Settle a payout from `transfer.success` / `transfer.failed` / `transfer.reversed`."""
    our_reference = event_data.get("reference") or ""
    if not our_reference.startswith("PAYOUT-"):
        return None
    try:
        withdrawal_id = int(our_reference.split("-")[1])
    except (IndexError, ValueError):
        logger.warning("Transfer webhook with unparsable reference %s", our_reference[:32])
        return None
    withdrawal = (
        Withdrawal.objects.filter(id=withdrawal_id)
        .select_related("user", "payout_account")
        .first()
    )
    if not withdrawal:
        logger.warning("Transfer webhook for unknown withdrawal %s", withdrawal_id)
        return None
    if not withdrawal.external_reference:
        withdrawal.external_reference = event_data.get("transfer_code") or our_reference
        withdrawal.save(update_fields=["external_reference"])
    settle_with_transfer_status(withdrawal, event_data.get("status"))
    return withdrawal
