from django.contrib import admin, messages
from django.utils import timezone

from .models import PayoutAccount, Transaction, Withdrawal
from .services import attempt_paystack_transfer, ensure_paystack_recipient


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
    search_fields = ("reference", "user__email", "course__title", "paystack_id")
    readonly_fields = ("reference", "amount_minor", "platform_fee_minor", "raw_response")


@admin.register(PayoutAccount)
class PayoutAccountAdmin(admin.ModelAdmin):
    list_display = (
        "user", "kind", "provider_name", "masked_account", "account_name",
        "recipient_code", "is_active",
    )
    list_filter = ("kind", "is_active")
    search_fields = ("user__email", "account_name", "account_number")
    readonly_fields = ("recipient_code",)
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
        "account_number", "created", "processed_at",
    )
    list_filter = ("status", "paid_via", "kind")
    search_fields = ("user__email", "external_reference", "account_name", "account_number")
    readonly_fields = (
        "user", "amount_minor", "payout_account", "kind", "provider_name",
        "account_number", "account_name", "bank_code", "created",
    )
    date_hierarchy = "created"
    actions = ["mark_paid_manual", "pay_via_paystack", "reject_requests"]

    @admin.action(description="Mark selected as PAID (settled manually)")
    def mark_paid_manual(self, request, queryset):
        updated = queryset.filter(status=Withdrawal.Status.REQUESTED).update(
            status=Withdrawal.Status.PAID,
            paid_via=Withdrawal.PaidVia.MANUAL,
            processed_at=timezone.now(),
        )
        messages.success(request, f"{updated} payout(s) marked as paid.")

    @admin.action(description="Pay selected via Paystack Transfer")
    def pay_via_paystack(self, request, queryset):
        for withdrawal in queryset.filter(status=Withdrawal.Status.REQUESTED):
            paid, message = attempt_paystack_transfer(withdrawal)
            messages.add_message(
                request,
                messages.SUCCESS if paid else messages.ERROR,
                f"#{withdrawal.id} {withdrawal.user.email}: {message}",
            )

    @admin.action(description="Reject selected payout requests")
    def reject_requests(self, request, queryset):
        updated = queryset.filter(status=Withdrawal.Status.REQUESTED).update(
            status=Withdrawal.Status.REJECTED, processed_at=timezone.now()
        )
        messages.success(request, f"{updated} payout request(s) rejected (balance released).")
