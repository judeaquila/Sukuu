from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import User
from courses.models import Course


class Transaction(models.Model):
    """A Paystack transaction for a paid course purchase."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="transactions",
        help_text="Null for guest checkouts that pay before creating an account",
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="transactions")
    reference = models.CharField(max_length=80, unique=True, db_index=True)
    email = models.EmailField(default="", blank=True, help_text="Payer email (user's, or entered at checkout as a guest)")
    full_name = models.CharField(max_length=120, blank=True)
    amount_minor = models.PositiveIntegerField(help_text="Total the student paid, in pesewas")
    discount_minor = models.PositiveIntegerField(
        default=0, help_text="Coupon saving: list price minus what the student paid, in pesewas",
    )
    coupon = models.ForeignKey(
        "Coupon", on_delete=models.SET_NULL, blank=True, null=True, related_name="transactions",
    )
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
    def price_list_minor(self):
        """The course's list price before any coupon saving."""
        return self.amount_minor + self.discount_minor

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
    account_name = models.CharField(max_length=80, default="", blank=True, help_text="Registered name on the account")
    verified_name = models.CharField(
        max_length=80, blank=True,
        help_text="Account name resolved from Paystack (bank accounts are verified before saving)",
    )
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
        PROCESSING = "processing", "Processing (Paystack transfer initiated)"
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

class Coupon(models.Model):
    """A discount code a creator dishes out for their courses.

    Savings are computed against each course's list price at checkout:
    percent coupons take a % off, amount coupons take a fixed GH₵ amount off.
    """

    class Kind(models.TextChoices):
        PERCENT = "percent", "Percentage off"
        AMOUNT = "amount", "Fixed amount off (GHS)"

    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="coupons")
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, blank=True, null=True, related_name="coupons",
        help_text="Leave empty to apply to ALL of this creator's paid courses.",
    )
    code = models.CharField(max_length=24, unique=True, db_index=True, help_text="Stored uppercase, case-insensitive lookup")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PERCENT)
    value = models.PositiveIntegerField(
        help_text="Percentage (1-99) for percent coupons; pesewas off for amount coupons",
    )
    max_redemptions = models.PositiveIntegerField(null=True, blank=True, help_text="Empty = unlimited")
    times_used = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.code} ({self.kind}: {self.display_value})"

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    @property
    def display_value(self):
        if self.kind == self.Kind.PERCENT:
            return f"{self.value}% off"
        return f"GH₵{self.value / 100:,.2f} off"

    @property
    def is_expired(self):
        return bool(self.expires_at and self.expires_at < timezone.now())

    @property
    def redemption_left(self):
        if self.max_redemptions is None:
            return None
        return max(self.max_redemptions - self.times_used, 0)

    @property
    def has_redemptions_left(self):
        return self.max_redemptions is None or self.times_used < self.max_redemptions

    def discount_for(self, course):
        """Savings (pesewas) this coupon gives on a course's list price."""
        list_minor = course.price_minor
        if self.kind == self.Kind.PERCENT:
            return list_minor * self.value // 100
        return min(self.value, list_minor)

    def applies_to(self, course):
        return self.course is None or self.course == course
