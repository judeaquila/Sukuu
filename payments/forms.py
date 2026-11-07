from django import forms

from .models import PayoutAccount


# Known mobile-money provider codes on Paystack for Ghana.
MOMO_PROVIDERS = [
    ("mtn", "MTN Mobile Money"),
    ("vod", "Telecel Cash (Vodafone)"),
    ("atl", "AirtelTigo Money"),
]


class PayoutAccountForm(forms.ModelForm):
    class Meta:
        model = PayoutAccount
        fields = ("kind", "provider_code", "account_number", "account_name")
        widgets = {
            "provider_code": forms.Select(attrs={"class": "w-full rounded-lg border-gray-300"}),
        }

    def __init__(self, *args, bank_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "provider_code":
                field.widget.attrs["class"] = (
                    field.widget.attrs.get("class", "")
                    + " w-full rounded-lg border-gray-300 focus:border-green-600 focus:ring-green-600"
                ).strip()

        # Payout providers: MoMo providers always; GH banks listed when Paystack's
        # bank list is reachable (needs API keys + network).
        providers = [code for code, _ in MOMO_PROVIDERS]
        provider_options = list(MOMO_PROVIDERS)
        for choice in bank_choices or []:
            if choice[0] not in providers:
                provider_options.append(choice)
                providers.append(choice[0])
        self.fields["provider_code"].widget.choices = provider_options

    def clean(self):
        data = super().clean()
        code = data.get("provider_code")
        labels = dict(self.fields["provider_code"].widget.choices)
        if code and code in labels:
            data["provider_name"] = labels[code]
        else:
            raise forms.ValidationError("Choose a payout provider.")
        return data


class WithdrawalRequestForm(forms.Form):
    payout_account = forms.ModelChoiceField(
        queryset=PayoutAccount.objects.none(),
        label="Pay out to",
        widget=forms.Select(attrs={"class": "w-full rounded-lg border-gray-300"}),
    )
    amount = forms.DecimalField(
        label="Amount (GHS)",
        min_value=0.01,
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "0.01", "class": "w-full rounded-lg border-gray-300"}),
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
