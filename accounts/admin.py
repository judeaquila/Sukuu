from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import CreatorProfile

User = get_user_model()


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """User admin tuned for the email-based custom user model."""

    list_display = ("email", "full_name", "role", "country", "is_staff", "date_joined")
    list_filter = ("role", "is_staff", "country")
    search_fields = ("email", "full_name")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "phone", "country")}),
        ("Role", {"fields": ("role",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "full_name", "role", "password1", "password2")}),
    )


@admin.register(CreatorProfile)
class CreatorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "headline", "website")
    search_fields = ("user__email", "user__full_name", "headline")
