from django.conf import settings
from django.db import models

from accounts.models import User
from courses.models import Course


class Transaction(models.Model):
    """A Paystack transaction for a paid course purchase."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="transactions")
    reference = models.CharField(max_length=80, unique=True, db_index=True)
    amount_minor = models.PositiveIntegerField(help_text="Total the student paid, in pesewas")
    currency = models.CharField(max_length=8, default=settings.CURRENCY)
    platform_fee_minor = models.PositiveIntegerField(default=0, help_text="Platform commission, in pesewas")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    paystack_id = models.CharField(max_length=64, blank=True)
    payment_channel = models.CharField(max_length=40, blank=True, help_text="card / momo / bank …")
    raw_response = models.JSONField(blank=True, null=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.reference} — {self.status}"

    def save(self, *args, **kwargs):
        if not self.platform_fee_minor and self.status == self.Status.SUCCESS:
            # 10% (configurable) commission on each sale → rest is the creator's earnings
            self.platform_fee_minor = (
                self.amount_minor * settings.PLATFORM_COMMISSION_PERCENT // 100
            )
        super().save(*args, **kwargs)

    @property
    def amount(self):
        return self.amount_minor / 100

    @property
    def platform_fee(self):
        return self.platform_fee_minor / 100

    @property
    def creator_earnings(self):
        return (self.amount_minor - self.platform_fee_minor) / 100


class PayoutAccount(models.Model):
    """Where a creator wants their money sent: Mobile Money or bank account."""

    class Kind(models.TextChoices):
        MOMO = "momo", "Mobile Money"
        BANK = "bank", "Bank account"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payout_accounts")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MOMO)
    provider_code = models.CharField(
        max_length=20,
        help_text="Paystack bank/provider code, e.g. mtn, vod, atl for MoMo, or the bank's code",
    )
    provider_name = models.CharField(max_length=80, help_text="Display name, e.g. MTN Mobile Money")
    account_number = models.CharField(max_length=20, help_text="MoMo number or bank account number")
    account_name = models.CharField(max_length=80, help_text="Registered name on the account")
    recipient_code = models.CharField(
        max_length=40, blank=True,
        help_text="Paystack transfer recipient code (auto-created when the API is configured)",
    )
    is_active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.provider_name} ·····{self.account_number[-4:]} ({self.user.email})"

    @property
    def masked_account(self):
        return f"····{self.account_number[-4:]}" if len(self.account_number) >= 4 else self.account_number


class Withdrawal(models.Model):
    """A creator payout request. The platform settles it manually or via Paystack Transfers."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        PAID = "paid", "Paid"
        REJECTED = "rejected", "Rejected"

    class PaidVia(models.TextChoices):
        MANUAL = "manual", "Manual (outside Paystack)"
        PAYSTACK = "paystack", "Paystack Transfer"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="withdrawals")
    amount_minor = models.PositiveIntegerField(help_text="Payout amount, in pesewas")
    payout_account = models.ForeignKey(
        PayoutAccount, on_delete=models.SET_NULL, blank=True, null=True, related_name="withdrawals"
    )
    # Denormalised snapshot so the payment details survive account edits/deletion
    kind = models.CharField(max_length=10, choices=PayoutAccount.Kind.choices, default=PayoutAccount.Kind.MOMO)
    provider_name = models.CharField(max_length=80, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    account_name = models.CharField(max_length=80, blank=True)
    bank_code = models.CharField(max_length=20, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    paid_via = models.CharField(
        max_length=20, choices=PaidVia.choices, default=PaidVia.MANUAL
    )
    external_reference = models.CharField(max_length=80, blank=True, help_text="Paystack transfer code")
    note = models.CharField(max_length=250, blank=True)
    processed_at = models.DateTimeField(blank=True, null=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.user} — {self.amount_minor / 100:.2f} ({self.status})"

    @property
    def amount(self):
        return self.amount_minor / 100

    def snapshot_account(self):
        """Copy the payment details from the linked payout account (if any)."""
        if self.payout_account:
            account = self.payout_account
            self.kind = account.kind
            self.provider_name = account.provider_name
            self.account_number = account.account_number
            self.account_name = account.account_name
            self.bank_code = account.provider_code