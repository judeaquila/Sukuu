from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils import timezone

from .models import PayoutAccount, Transaction, Withdrawal
from .services import (
    attempt_paystack_transfer,
    ensure_paystack_recipient,
    notify_withdrawal_status,
)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "user",
        "course",
        "amount",
        "platform_fee",
        "status",
        "payment_channel",
        "created",
    )
    list_filter = ("status", "payment_channel", "currency")
    search_fields = ("reference", "email", "user__email", "course__title", "paystack_id")
    readonly_fields = ("reference", "amount_minor", "platform_fee_minor", "raw_response")


@admin.register(PayoutAccount)
class PayoutAccountAdmin(admin.ModelAdmin):
    list_display = (
        "user", "kind", "provider_name", "masked_account", "account_name",
        "recipient_code", "is_active",
    )
    list_filter = ("kind", "is_active")
    search_fields = ("user__email", "account_name", "account_number")
    readonly_fields = ("recipient_code", "verified_name")
    actions = ["create_recipient"]

    @admin.display(description="Account")
    def masked_account(self, obj):
        return obj.masked_account

    @admin.action(description="Create Paystack recipient for selected accounts")
    def create_recipient(self, request, queryset):
        for account in queryset.filter(recipient_code=""):
            code, error = ensure_paystack_recipient(account)
            messages.add_message(
                request,
                messages.SUCCESS if code else messages.ERROR,
                f"{account}: {code or error}",
            )


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = (
        "user", "amount", "status", "paid_via", "provider_name",
        "account_number", "external_reference", "created", "processed_at",
    )
    list_filter = ("status", "paid_via", "kind")
    search_fields = ("user__email", "external_reference", "account_name", "account_number")
    readonly_fields = (
        "user", "amount_minor", "payout_account", "kind", "provider_name",
        "account_number", "account_name", "bank_code", "external_reference", "created",
    )
    date_hierarchy = "created"
    actions = ["mark_paid_manual", "pay_via_paystack", "requery_processing", "reject_requests"]

    @admin.action(description="Mark selected as PAID (settled manually)")
    def mark_paid_manual(self, request, queryset):
        requested = queryset.filter(status=Withdrawal.Status.REQUESTED)
        skipped = queryset.exclude(status=Withdrawal.Status.REQUESTED).count()
        for withdrawal in requested:
            withdrawal.status = Withdrawal.Status.PAID
            withdrawal.paid_via = Withdrawal.PaidVia.MANUAL
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=["status", "paid_via", "processed_at"])
            notify_withdrawal_status(withdrawal)
        messages.success(request, f"{requested.count()} payout(s) marked as paid; creators notified.")
        if skipped:
            messages.info(request, f"{skipped} selection(s) skipped — not in 'Requested' state.")

    @admin.action(description="Reject selected payout requests (ask for a reason…)")
    def reject_requests(self, request, queryset):
        """Intermediate form: collect a reason that reaches the creator."""
        ids = list(
            queryset.filter(status=Withdrawal.Status.REQUESTED).values_list("id", flat=True)
        )
        skipped = queryset.exclude(status=Withdrawal.Status.REQUESTED).count()
        if skipped:
            messages.warning(request, f"{skipped} selection(s) skipped — not in 'Requested' state.")
        if not ids:
            if not skipped:
                messages.info(request, "Nothing to reject.")
            return None
        return redirect(
            f"{reverse('admin:payments_withdrawal_reject')}?ids={','.join(str(i) for i in ids)}"
        )

    def get_urls(self):
        return [
            path(
                "reject/",
                self.admin_site.admin_view(self.reject_view),
                name="payments_withdrawal_reject",
            ),
            *super().get_urls(),
        ]

    def reject_view(self, request):
        id_csv = request.GET.get("ids") or request.POST.get("ids") or ""
        ids = [int(x) for x in id_csv.split(",") if x.isdigit()]
        withdrawals = Withdrawal.objects.filter(
            id__in=ids, status=Withdrawal.Status.REQUESTED
        ).select_related("user", "payout_account")

        if request.method == "POST":
            reason = (request.POST.get("reason") or "").strip()
            for withdrawal in withdrawals:
                withdrawal.status = Withdrawal.Status.REJECTED
                withdrawal.paid_via = Withdrawal.PaidVia.MANUAL
                withdrawal.note = reason
                withdrawal.processed_at = timezone.now()
                withdrawal.save(update_fields=["status", "paid_via", "note", "processed_at"])
                notify_withdrawal_status(withdrawal)
            messages.success(
                request,
                f"{withdrawals.count()} payout(s) rejected — funds released and creators notified.",
            )
            return redirect("admin:payments_withdrawal_changelist")

        return render(
            request,
            "admin/payments/withdrawal/reject_form.html",
            {
                "withdrawals": withdrawals,
                "ids": id_csv,
            },
        )
    @admin.action(description="Pay selected via Paystack Transfer")
    def pay_via_paystack(self, request, queryset):
        for withdrawal in queryset.filter(status=Withdrawal.Status.REQUESTED):
            moved, message = attempt_paystack_transfer(withdrawal)
            messages.add_message(
                request,
                messages.SUCCESS if moved else messages.ERROR,
                f"#{withdrawal.id} {withdrawal.user.email}: {message}",
            )

    @admin.action(description="Re-query PROCESSING transfers with Paystack")
    def requery_processing(self, request, queryset):
        from payments.paystack import PaystackAPI, PaystackPayoutError
        from .services import settle_with_transfer_status

        for withdrawal in queryset.filter(status=Withdrawal.Status.PROCESSING).exclude(external_reference=""):
            try:
                data = PaystackAPI().fetch_transfer(withdrawal.external_reference)
            except PaystackPayoutError as exc:
                messages.error(request, f"#{withdrawal.id}: {exc}")
                continue
            before = withdrawal.status
            settle_with_transfer_status(withdrawal, (data or {}).get("status"))
            if withdrawal.status != before:
                messages.add_message(
                    request, messages.SUCCESS,
                    f"#{withdrawal.id} settled: {withdrawal.get_status_display()}",
                )
            else:
                messages.add_message(
                    request, messages.INFO,
                    f"#{withdrawal.id} still {withdrawal.status} (Paystack: {(data or {}).get('status')})",
                )
