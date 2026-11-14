from django import forms

from .models import Coupon, PayoutAccount


# Fallback mobile-money providers when Paystack's live list is unreachable.
# Codes match Paystack's API (uppercase, per the docs).
MOMO_PROVIDERS = [
    ("MTN", "MTN Mobile Money"),
    ("VOD", "Telecel Cash (Vodafone)"),
    ("ATL", "AirtelTigo Money"),
]


class PayoutAccountForm(forms.ModelForm):
    """Add/edit a payout destination.

    Provider options come in two optgroups — Mobile Money and Banks — and the
    template's JS only shows the group matching the chosen account type. The
    server enforces it again in clean() so mismatched codes can't be saved.
    """

    class Meta:
        model = PayoutAccount
        fields = ("kind", "provider_code", "account_number", "account_name")
        widgets = {
            "provider_code": forms.Select(attrs={
                "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand"
            }),
        }

    def __init__(self, *args, momo=None, banks=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "provider_code":
                field.widget.attrs["class"] = (
                    field.widget.attrs.get("class", "")
                    + " w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
                    "outline-none focus:border-brand focus:ring-1 focus:ring-brand"
                ).strip()

        # Live MoMo list when available; static fallback otherwise.
        momo = list(momo or []) or [{"code": c, "name": n} for c, n in MOMO_PROVIDERS]
        banks = list(banks or [])

        self._allowed = {
            "momo": {p["code"] for p in momo},
            "bank": {b["code"] for b in banks},
        }
        self._labels = {
            **{p["code"]: p["name"] for p in momo},
            **{b["code"]: b["name"] for b in banks},
        }

        choices = []
        if momo:
            choices.append(("Mobile Money", [(p["code"], p["name"]) for p in momo]))
        if banks:
            choices.append(("Banks", [(b["code"], b["name"]) for b in banks]))
        if not choices:  # API unreachable and no fallback — shouldn't happen
            choices.append(("Mobile Money", [(c, n) for c, n in MOMO_PROVIDERS]))
        # provider_code is a CharField: grouped options must live on the widget
        self.fields["provider_code"].widget.choices = choices

    def clean(self):
        data = super().clean()
        kind = data.get("kind") or PayoutAccount.Kind.MOMO
        code = data.get("provider_code")
        allowed = self._allowed.get(kind, set())
        if not code or code not in allowed:
            raise forms.ValidationError(
                "Choose a valid provider for the selected account type."
            )
        data["provider_name"] = self._labels.get(code, code)
        return data


class WithdrawalRequestForm(forms.Form):
    payout_account = forms.ModelChoiceField(
        queryset=PayoutAccount.objects.none(),
        label="Pay out to",
        widget=forms.Select(attrs={
            "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand"
        }),
    )
    amount = forms.DecimalField(
        label="Amount (GHS)",
        min_value=0.01,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            "step": "0.01",
            "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-brand focus:ring-1 focus:ring-brand",
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["payout_account"].queryset = PayoutAccount.objects.filter(
                user=user, is_active=True
            )
            self.fields["payout_account"].label_from_instance = (
                lambda a: f"{a.provider_name} {a.masked_account} — {a.account_name}"
            )


class CouponForm(forms.ModelForm):
    """Create/edit a discount code.

    `value` is a single decimal whose meaning follows the coupon kind: a
    percentage (1-99) for percent coupons, or a GH₵ amount for amount coupons
    (converted to pesewas in clean()).
    """

    value = forms.DecimalField(
        min_value=1, max_digits=8, decimal_places=2,
        help_text="Percentage off (percent coupons) or GH₵ amount off (amount coupons)",
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="Empty = never expires",
    )

    class Meta:
        model = Coupon
        fields = ("code", "kind", "course", "max_redemptions", "expires_at", "is_active")
        labels = {"max_redemptions": "Maximum redemptions"}

    def __init__(self, *args, creator=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                continue  # checkboxes get their own styling
            field.widget.attrs.setdefault(
                "class",
                "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm "
                "outline-none focus:border-brand focus:ring-1 focus:ring-brand",
            )
        self.fields["code"].widget.attrs["class"] += " uppercase"
        if creator is not None:
            from courses.models import Course

            self.fields["course"].queryset = Course.objects.filter(
                creator=creator, status=Course.Status.PUBLISHED
            )
        else:
            self.fields["course"].queryset = Coupon.objects.none()
        self.fields["course"].empty_label = "All my paid courses"
        self.fields["expires_at"].widget.input_formats = (
            "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M",
        )
        if self.instance and self.instance.kind == Coupon.Kind.AMOUNT and self.instance.pk:
            self.fields["value"].initial = self.instance.value / 100
        if self.instance and self.instance.pk:
            self.fields["code"].disabled = True

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("Enter a coupon code.")
        qs = Coupon.objects.filter(code__iexact=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That code is already in use — pick another.")
        return code

    def clean(self):
        data = super().clean()
        kind = data.get("kind") or Coupon.Kind.PERCENT
        value = data.get("value")
        if value is not None:
            if kind == Coupon.Kind.PERCENT:
                if not 1 <= value <= 99:
                    self.add_error("value", "Percentage off must be between 1 and 99.")
                data["value"] = int(value)
            else:
                data["value"] = int(value * 100)
        return data

    def save(self, commit=True):
        # `value` is a declared form field (not in Meta.fields), so the default
        # construct_instance() never moves cleaned_data onto the model instance.
        instance = super().save(commit=False)
        instance.value = self.cleaned_data.get("value") or 0
        if commit:
            instance.save()
        return instance
