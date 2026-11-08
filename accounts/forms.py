from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import CreatorProfile, User


class SignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("full_name", "email", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} w-full rounded-lg border-gray-300 focus:border-green-600 focus:ring-green-600".strip()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email
        if commit:
            user.save()
            if user.is_creator:
                CreatorProfile.objects.get_or_create(user=user)
        return user

class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("full_name", "phone", "country", "avatar")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-brand focus:ring-1 focus:ring-brand outline-none".strip()

class CreatorProfileForm(forms.ModelForm):
    class Meta:
        model = CreatorProfile
        fields = ("headline", "bio", "website")
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} w-full rounded-lg border-gray-300 focus:border-green-600 focus:ring-green-600".strip()
