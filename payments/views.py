import json
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from courses.models import enrollment_for
from payments.forms import MOMO_PROVIDERS, PayoutAccountForm, WithdrawalRequestForm
from payments.models import PayoutAccount, Transaction, Withdrawal
from payments.paystack import PaystackAPI, PaystackPayoutError, PaystackVerificationError
from payments.services import (
    apply_transaction,
    attempt_paystack_transfer,
    creator_balance_minor,
    creator_earnings_totals,
    ensure_paystack_recipient,
    handle_webhook_event,
)


def _pending_redirect(request, transaction):
    """Where the buyer goes after the payment modal closes/verifies."""
    messages.success(
        request, f"Payment successful — you have access to “{transaction.course.title}”!"
    )
    return redirect("courses:course_detail", transaction.course.slug)


@login_required
def course_checkout(request, slug):
    """Start a paid course checkout and open the Paystack inline modal.

    Guests can't pay directly: the course page sends them to signup first,
    and they return to the course page (via ?next=) to make the payment.
    """
    from courses.models import Course

    course = get_object_or_404(Course, slug=slug, status=Course.Status.PUBLISHED)

    enrollment = enrollment_for(request.user, course)
    if enrollment:
        messages.info(request, "You already have access to this course.")
        return redirect("accounts:my_learning")

    if request.method != "POST":
        return redirect("courses:course_detail", slug)

    user = request.user
    reference = f"OLTSCH-{uuid.uuid4().hex[:12].upper()}"
    transaction = Transaction.objects.create(
        user=user,
        course=course,
        reference=reference,
        email=user.email,
        full_name=user.full_name or "",
        amount_minor=course.price_minor,
        currency=settings.CURRENCY,
        status=Transaction.Status.PENDING,
    )

    context = {
        "transaction": transaction,
        "paystack_pub_key": settings.PAYSTACK_PUBLIC_KEY,
        "trigger_paystack": True,
        "amount_value": transaction.amount_minor,
    }
    return render(request, "payments/pay_modal.html", context)


def callback(request):
    """The inline modal redirects here after payment."""
    reference = request.GET.get("reference") or request.GET.get("trxref")
    if not reference:
        return HttpResponseBadRequest("Missing reference.")
    transaction = get_object_or_404(Transaction, reference=reference)

    if transaction.status == Transaction.Status.SUCCESS:
        return _pending_redirect(request, transaction)

    try:
        api = PaystackAPI()
        data = api.verify(reference)
    except PaystackVerificationError as exc:
        messages.error(request, f"We could not confirm your payment: {exc}")
        return redirect("courses:course_detail", transaction.course.slug)

    apply_transaction(transaction, paystack_data=data)
    if transaction.status == Transaction.Status.SUCCESS:
        return _pending_redirect(request, transaction)

    if transaction.status == Transaction.Status.FAILED:
        messages.error(
            request,
            "Payment failed or the amount didn't match. No charges or access were granted — please try again.",
        )
    else:
        messages.warning(
            request,
            "Payment is not confirmed yet. If you completed it, access will be granted shortly.",
        )
    return redirect("courses:course_detail", transaction.course.slug)


def checkout_pending(request, reference):
    """Fallback page for a reference; shows its current status."""
    transaction = get_object_or_404(Transaction, reference=reference)
    return render(request, "payments/checkout_pending.html", {"transaction": transaction})


@login_required
def my_purchases(request):
    """Transactions for the logged-in student."""
    transactions = Transaction.objects.filter(
        user=request.user
    ).select_related("course").order_by("-created")
    return render(request, "payments/my_purchases.html", {"transactions": transactions})


@require_POST
@csrf_exempt  # external service; protected by HMAC signature check instead
def webhook(request):
    signature = request.headers.get("x-paystack-signature", "")
    api = PaystackAPI()
    if not api.verify_webhook_signature(request.body, signature):
        return HttpResponseForbidden("Invalid signature.")
    event = json.loads(request.body.decode("utf-8") or "{}")
    handle_webhook_event(event.get("event") or "", event.get("data") or {})
    return HttpResponse("ok")


# ---------------------------------------------------------------------------
# Creator payouts
# ---------------------------------------------------------------------------

MIN_PAYOUT_GHS = getattr(settings, "PLATFORM_MIN_PAYOUT", 50)


def _provider_lists():
    """Live GH banks + MoMo providers from Paystack.

    Returns {"banks": [{"code","name"}…], "momo": [{"code","name"}…]} or None
    when the API is unreachable (fallback handled by the form).
    """
    try:
        return PaystackAPI().list_banks()
    except PaystackPayoutError:
        return None


@login_required
def payouts(request):
    """Creator's payout page: balances, payout-account CRUD, requests & history."""
    user = request.user
    if not (user.is_creator or user.is_staff):
        messages.info(request, "Payouts are for course creators.")
        return redirect("courses:dashboard")

    earnings = creator_earnings_totals(user)
    balance_minor = creator_balance_minor(user)
    accounts = PayoutAccount.objects.filter(user=user, is_active=True)

    editing = None
    if request.GET.get("edit"):
        editing = get_object_or_404(PayoutAccount, pk=request.GET["edit"], user=user, is_active=True)
    providers = _provider_lists()
    account_form = PayoutAccountForm(instance=editing, banks=providers["banks"] if providers else None,
                                     momo=providers["momo"] if providers else None)
    withdrawal_form = WithdrawalRequestForm(user=user)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_account" or action == "edit_account":
            instance = None
            if action == "edit_account":
                instance = get_object_or_404(PayoutAccount, pk=request.POST.get("account_id"), user=user)
            # Snapshot BEFORE the form mutates the instance
            original_details = (
                (instance.account_number, instance.provider_code, instance.kind) if instance else None
            )
            account_form = PayoutAccountForm(
                request.POST, instance=instance,
                banks=providers["banks"] if providers else None,
                momo=providers["momo"] if providers else None,
            )
            if account_form.is_valid():
                account = account_form.save(commit=False)
                account.user = user
                # provider_name is derived in the form's clean(), not a declared field
                account.provider_name = account_form.cleaned_data["provider_name"]

                if instance is None:
                    _verify_and_link_account(request, account, is_new=True)
                else:
                    # Paystack recipients can't have their account number updated:
                    # number/provider changes need a fresh recipient.
                    details_changed = (
                        account.account_number != original_details[0]
                        or account.provider_code != original_details[1]
                        or account.kind != original_details[2]
                    )
                    if details_changed:
                        _verify_and_link_account(request, account, is_new=False)
                    else:
                        # Only the display name changed; keep the existing recipient
                        account.save(update_fields=["account_name", "provider_name"])
                        messages.success(request, "Account updated.")
                return redirect("payments:payouts")
            else:
                # Template re-renders with the errors below
                editing = instance
        elif action == "request_payout":
            withdrawal_form = WithdrawalRequestForm(request.POST, user=user)
            if withdrawal_form.is_valid():
                amount_minor = int(float(withdrawal_form.cleaned_data["amount"]) * 100)
                account = withdrawal_form.cleaned_data["payout_account"]
                if amount_minor > balance_minor:
                    messages.error(
                        request,
                        f"You can only withdraw up to your available balance "
                        f"(GH\N{CEDI SIGN}{balance_minor / 100:,.2f}).",
                    )
                elif amount_minor < MIN_PAYOUT_GHS * 100:
                    messages.error(request, f"The minimum payout is GH\N{CEDI SIGN}{MIN_PAYOUT_GHS:,.2f}.")
                else:
                    withdrawal = Withdrawal.objects.create(
                        user=user,
                        amount_minor=amount_minor,
                        payout_account=account,
                        status=Withdrawal.Status.REQUESTED,
                    )
                    withdrawal.snapshot_account()
                    withdrawal.save()
                    messages.success(
                        request,
                        "Payout requested! The Sukuu team will process it shortly — you can cancel it until it's sent.",
                    )
                    return redirect("payments:payouts")
            else:
                messages.error(request, "Please fix the highlighted errors.")

    context = {
        "earnings": earnings,
        "balance_minor": balance_minor,
        "locked_minor": earnings["earnings_minor"] - balance_minor,
        "accounts": accounts,
        "editing": editing,
        "account_form": account_form,
        "withdrawal_form": withdrawal_form,
        "history": Withdrawal.objects.filter(user=user)[:20],
        "min_payout": MIN_PAYOUT_GHS,
    }
    return render(request, "payments/payouts.html", context)


def _verify_and_link_account(request, account, is_new):
    """Save a payout account after verifying bank numbers, then link to Paystack.

    Paystack cannot update an account number on an existing recipient, so a
    changed number means: delete the old recipient and create a fresh one.
    """
    from payments.paystack import PaystackAPI, PaystackPayoutError

    def _touch_recipient(account):
        old_code = account.recipient_code
        account.recipient_code = ""
        if account.pk:
            account.save(update_fields=[
                "provider_code", "provider_name", "account_number",
                "account_name", "verified_name", "recipient_code",
            ])
        else:
            account.save()
        if old_code and not is_new:
            try:
                PaystackAPI().delete_transfer_recipient(old_code)
            except PaystackPayoutError as exc:
                messages.warning(request, f"Old Paystack recipient could not be deleted ({exc}).")
        code, error = ensure_paystack_recipient(account)
        if error:
            messages.warning(
                request,
                f"Account saved. Paystack recipient not created ({error}) — the platform will settle this account manually.",
            )
        else:
            messages.success(request, f"{account.provider_name} account saved and linked to Paystack!")

    api = PaystackAPI()
    if account.kind == PayoutAccount.Kind.BANK:
        try:
            account.verified_name = api.resolve_account_number(
                account_number=account.account_number, bank_code=account.provider_code
            )
            account.account_name = account.account_name or account.verified_name
        except PaystackPayoutError as exc:
            if not (account.account_name or "").strip():
                # Nothing typed and nothing resolved: we can't name this recipient
                if is_new:
                    messages.error(
                        request,
                        f"Paystack couldn't auto-verify that account ({exc}). "
                        "Type the registered account name to save it.",
                    )
                    return
            if is_new:
                messages.warning(
                    request,
                    f"Saved without Paystack auto-verification ({exc}) — "
                    "the name is taken as you entered it.",
                )
            else:
                messages.warning(
                    request,
                    f"Account updated, but verification failed ({exc}); "
                    "the recipient was re-linked with the name as entered.",
                )
        _touch_recipient(account)
    else:
        _touch_recipient(account)


@login_required
def payout_account_delete(request, pk):
    """Remove a payout account: delete its Paystack recipient and deactivate it."""
    if request.method != "POST":
        return redirect("payments:payouts")
    account = get_object_or_404(PayoutAccount, pk=pk, user=request.user)
    if account.recipient_code:
        try:
            PaystackAPI().delete_transfer_recipient(account.recipient_code)
        except PaystackPayoutError as exc:
            messages.warning(
                request,
                f"Payout account removed locally, but the Paystack recipient could not be deleted ({exc}).",
            )
    account.is_active = False
    account.recipient_code = ""
    account.save(update_fields=["is_active", "recipient_code"])
    messages.info(request, "Payout account removed.")
    return redirect("payments:payouts")


@login_required
def payout_account_verify(request):
    """Resolve the registered account name for a bank number (used by the
    payout form's JS so creators confirm the destination before saving)."""
    provider = request.GET.get("provider_code", "").strip()
    number = request.GET.get("account_number", "").strip()
    if not provider or not number:
        return JsonResponse({"error": "Enter the bank and account number first."})
    try:
        name = PaystackAPI().resolve_account_number(
            account_number=number, bank_code=provider
        )
    except PaystackPayoutError as exc:
        return JsonResponse({"error": str(exc)})
    return JsonResponse({"account_name": name})


@login_required
@require_POST
def payout_request_cancel(request, pk):
    """Cancel a payout request still awaiting processing (balance is released)."""
    withdrawal = get_object_or_404(
        Withdrawal, pk=pk, user=request.user, status=Withdrawal.Status.REQUESTED
    )
    withdrawal.status = Withdrawal.Status.REJECTED
    withdrawal.paid_via = Withdrawal.PaidVia.MANUAL
    withdrawal.note = "Cancelled by creator"
    withdrawal.processed_at = timezone.now()
    withdrawal.save(update_fields=["status", "paid_via", "note", "processed_at"])
    messages.info(request, "Payout request cancelled — the funds are back in your balance.")
    return redirect("payments:payouts")
