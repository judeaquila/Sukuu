import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

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


@login_required
def checkout_pending(request, reference):
    """Nothing further to do here: this page exists in case a student returns
    without a callback URL (we rely on Paystack's hosted checkout instead)."""
    transaction = get_object_or_404(
        Transaction, reference=reference, user=request.user
    )
    return render(request, "payments/checkout_pending.html", {"transaction": transaction})


@login_required
def callback(request):
    """Paystack redirects here after the hosted checkout with ?reference=… or ?trxref=…."""
    reference = request.GET.get("reference") or request.GET.get("trxref")
    if not reference:
        return HttpResponseBadRequest("Missing reference.")
    transaction = get_object_or_404(
        Transaction, reference=reference, user=request.user
    )

    try:
        api = PaystackAPI()
        data = api.verify(reference)
    except PaystackVerificationError as exc:
        messages.error(request, f"We could not confirm your payment: {exc}")
        return _result_redirect(transaction.course.slug)

    apply_transaction(transaction, paystack_data=data)
    if transaction.status == Transaction.Status.SUCCESS:
        messages.success(request, "Payment successful — enjoy the course!")
    else:
        messages.warning(
            request, "Payment is not confirmed yet. If you completed it, access will be granted shortly."
        )
    return _result_redirect(transaction.course.slug)


def _result_redirect(course_slug):
    return redirect("courses:course_detail", course_slug)


@require_POST
@csrf_exempt  # external service; protected by HMAC signature check instead
def webhook(request):
    signature = request.headers.get("x-paystack-signature", "")
    api = PaystackAPI()
    if not api.verify_webhook_signature(request.body, signature):
        return HttpResponseForbidden("Invalid signature.")
    event = json.loads(request.body.decode("utf-8") or "{}")
    if event.get("event") == "charge.success":
        handle_webhook_event(event.get("data") or {})
    return HttpResponse("ok")


# ---------------------------------------------------------------------------
# Creator payouts
# ---------------------------------------------------------------------------

MIN_PAYOUT_GHS = getattr(settings, "PLATFORM_MIN_PAYOUT", 50)


def _bank_choices():
    """Fetch GH banks + MoMo providers from Paystack; None when unavailable."""
    try:
        data = PaystackAPI().list_banks()
    except PaystackPayoutError:
        return None
    choices, seen = [], set()
    for bank in data:
        code, name = bank.get("code"), bank.get("name")
        if code and name and code not in {c for c, _ in choices}:
            choices.append((code, name))
            seen.add(code)
    return choices


@login_required
def payouts(request):
    """Creator's payout page: balances, payout accounts, withdrawal requests & history."""
    user = request.user
    if not (user.is_creator or user.is_staff):
        messages.info(request, "Payouts are for course creators.")
        return redirect("courses:dashboard")

    earnings = creator_earnings_totals(user)
    balance_minor = creator_balance_minor(user)
    accounts = PayoutAccount.objects.filter(user=user, is_active=True)

    account_form = PayoutAccountForm(bank_choices=_bank_choices())
    withdrawal_form = WithdrawalRequestForm(user=user)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_account":
            account_form = PayoutAccountForm(
                request.POST, bank_choices=_bank_choices()
            )
            if account_form.is_valid():
                account = account_form.save(commit=False)
                account.user = user
                # provider_name is derived in the form's clean(), not a declared field
                account.provider_name = account_form.cleaned_data["provider_name"]
                account.save()
                if not account.recipient_code:
                    code, error = ensure_paystack_recipient(account)
                    if error:
                        messages.warning(
                            request,
                            f"Account saved. Paystack recipient not created yet ({error}) — "
                            "the platform will settle this account manually.",
                        )
                    else:
                        messages.success(request, "Account saved and linked to Paystack!")
                else:
                    messages.success(request, "Account saved and linked to Paystack!")
                return redirect("payments:payouts")
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
                        "Payout requested! The Sukuu team will process it shortly — you'll be notified when it's sent.",
                    )
                    return redirect("payments:payouts")
            else:
                messages.error(request, "Please fix the highlighted errors.")

    context = {
        "earnings": earnings,
        "balance_minor": balance_minor,
        "locked_minor": earnings["earnings_minor"] - balance_minor,
        "accounts": accounts,
        "account_form": account_form,
        "withdrawal_form": withdrawal_form,
        "history": Withdrawal.objects.filter(user=user)[:20],
        "min_payout": MIN_PAYOUT_GHS,
    }
    return render(request, "payments/payouts.html", context)


@login_required
def payout_account_delete(request, pk):
    """Deactivate a payout account (keeps historical records intact)."""
    if request.method != "POST":
        return redirect("payments:payouts")
    account = get_object_or_404(PayoutAccount, pk=pk, user=request.user)
    account.is_active = False
    account.save(update_fields=["is_active"])
    messages.info(request, "Payout account removed.")
    return redirect("payments:payouts")
