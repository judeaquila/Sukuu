from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.base_user import BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Manager for the email-first user model (no usernames)."""

    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.CREATOR)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Platform user. Students buy & learn; Creators sell courses."""

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        CREATOR = "creator", "Creator"

    username = None  # users identify by email instead
    email = models.EmailField("email address", unique=True)

    full_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.STUDENT
    )
    phone = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="GH")
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email

    @property
    def is_creator(self):
        return self.role == self.Role.CREATOR

    @property
    def avatar_url(self):
        """Returns the avatar URL from user model, creator profile, or None."""
        # Check if the main user model has an avatar
        if self.avatar:
            return self.avatar.url
        
        # If they're a creator, check their creator profile avatar
        try:
            if self.is_creator and hasattr(self, "creator_profile") and self.creator_profile.avatar:
                return self.creator_profile.avatar.url
        except Exception:
            pass
            
        return None

    @property
    def initial(self):
        """Returns the first letter of the full name or email for fallback."""
        name = self.full_name or self.email
        return name[:1].upper() if name else ""


class CreatorProfile(models.Model):
    """Public-facing profile for creators who sell on the platform."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="creator_profile"
    )
    headline = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    website = models.URLField(blank=True)

    def __str__(self):
        return f"Creator profile: {self.user}"
