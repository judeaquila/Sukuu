from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from courses.models import Enrollment
from .forms import CreatorProfileForm, SignUpForm, UserProfileForm
from .models import User


class EmailAuthenticationForm(forms.Form):
    """Login with email + password (users don't have usernames)."""

    email = forms.EmailField(widget=forms.EmailInput(attrs={"autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput, strip=False)

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault(
                "class",
                "w-full rounded-lg border-gray-300 focus:border-green-600 focus:ring-green-600",
            )

    def clean(self):
        data = super().clean()
        self.user_cache = authenticate(
            request=self.request,
            username=data.get("email"),
            password=data.get("password"),
        )
        if self.user_cache is None:
            raise forms.ValidationError("Invalid email or password.")
        data["user"] = self.user_cache
        return data

    def get_user(self):
        return getattr(self, "user_cache", None)


def signup(request):
    if request.user.is_authenticated:
        return redirect(_next_url(request) or _post_login_url(request.user))

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(
                request, f"Akwaaba! Welcome to the school, {user.full_name or user.email}!"
            )
            return redirect(_next_url(request) or _post_login_url(user))
    else:
        form = SignUpForm()
    return render(request, "accounts/signup.html", {"form": form})


def _next_url(request):
    """A ?next= destination (course page etc.) after logging in / signing up."""
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    return candidate if candidate.startswith("/") and not candidate.startswith("//") else ""


def user_login(request):
    if request.user.is_authenticated:
        return redirect(_next_url(request) or _post_login_url(request.user))
    if request.method == "POST":
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            auth_login(request, user)
            return redirect(_next_url(request) or _post_login_url(user))
    else:
        form = EmailAuthenticationForm()
    return render(request, "accounts/login.html", {"form": form})


def _post_login_url(user):
    if user.is_creator:
        return reverse("courses:dashboard")
    return reverse("accounts:my_learning")


@login_required
def my_learning(request):
    """Courses the current student is enrolled in, grouped by progress."""
    enrollments = (
        Enrollment.objects.filter(user=request.user, is_active=True)
        .select_related("course", "course__creator")
        .order_by("-created")
    )
    return render(request, "accounts/my_learning.html", {"enrollments": enrollments})


@login_required
def profile_edit(request):
    user = request.user
    creator_profile = getattr(user, "creator_profile", None)

    if request.method == "POST":
        user_form = UserProfileForm(request.POST, request.FILES, instance=user)
        creator_form = (
            CreatorProfileForm(request.POST, instance=creator_profile)
            if user.is_creator and creator_profile
            else None
        )

        if user_form.is_valid() and (creator_form is None or creator_form.is_valid()):
            user_form.save()
            if creator_form:
                creator_form.save()
            messages.success(request, "Your profile has been updated successfully.")
            return redirect("accounts:my_learning")
    else:
        user_form = UserProfileForm(instance=user)
        creator_form = (
            CreatorProfileForm(instance=creator_profile)
            if user.is_creator and creator_profile
            else None
        )

    context = {
        "user_form": user_form,
        "creator_form": creator_form,
    }
    return render(request, "accounts/profile_edit.html", context)


def creator_public(request, username):
    """Landing page for a creator's school in the marketplace."""
    creator = get_object_or_404(User, email=username, role=User.Role.CREATOR)
    from courses.models import Course

    courses = creator.courses.filter(status=Course.Status.PUBLISHED)
    return render(
        request,
        "accounts/creator_public.html",
        {"creator": creator, "courses": courses},
    )
