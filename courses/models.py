from django.conf import settings
from django.db import models
from django.db.models import Max
from django.urls import reverse
from django.utils.text import slugify


class Course(models.Model):
    """A paid or free course created and marketed by a creator."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    class Category(models.TextChoices):
        BUSINESS = "business", "Business & Entrepreneurship"
        TECH = "tech", "Technology & Software"
        DESIGN = "design", "Design, Graphics & Video"
        MARKETING = "marketing", "Digital Marketing"
        AGRICULTURE = "agriculture", "Agriculture & Agribusiness"
        FASHION = "fashion", "Fashion & Beauty"
        ARTS = "arts", "Music & Creative Arts"
        FINANCE = "finance", "Personal Finance & Investing"
        HEALTH = "health", "Health & Wellness"
        EDUCATION = "education", "Education & Teaching"
        TRADES = "trades", "Trades & Handicrafts"
        LANGUAGES = "languages", "Language & Communication"
        COOKING = "cooking", "Cooking & Food"
        OTHER = "other", "Other"

    class Level(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="courses"
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True, allow_unicode=False)
    summary = models.CharField(max_length=200, help_text="One-liner shown on the marketplace card")
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.OTHER)
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.BEGINNER)
    cover_image = models.ImageField(upload_to="covers/", blank=True, null=True)
    # Price in major GHS units; 0 means free.
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="GHS. Set 0 to make it free.")
    # Compare-at ("old") price shown struck-through when it's above the price.
    original_price = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Old (compare-at) price for promos — shown struck-through when higher than the price.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "course"
            slug, i = base, 2
            while Course.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def is_free(self):
        return self.price == 0

    @property
    def price_minor(self):
        """Price in pesewas, for Paystack."""
        return int(self.price * 100)

    @property
    def original_price_minor(self):
        return int(self.original_price * 100) if self.original_price else None

    @property
    def is_on_promo(self):
        return bool(self.original_price and self.original_price > self.price and not self.is_free)

    @property
    def promo_percent(self):
        if not self.is_on_promo:
            return None
        return round((1 - self.price / self.original_price) * 100)

    @property
    def promo_savings(self):
        """Cedis saved when buying at the promo price."""
        if not self.is_on_promo:
            return None
        return self.original_price - self.price

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    def get_absolute_url(self):
        return reverse("courses:course_detail", args=[self.slug])


class Module(models.Model):
    """A section of a course containing ordered lessons."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules_related")
    title = models.CharField(max_length=200)
    order = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.course.title} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.order:
            agg = Module.objects.filter(course=self.course).aggregate(Max("order"))
            self.order = (agg["order__max"] or 0) + 1
        super().save(*args, **kwargs)


class Lesson(models.Model):
    """A single lesson: a video (uploaded / YouTube / Vimeo / MP4 link), an
    optional audio version, plus written content."""

    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    video_url = models.URLField(blank=True, help_text="External YouTube or Vimeo link")
    video_file = models.FileField(
        upload_to="lessons/videos/", blank=True, null=True,
        help_text="Or upload a video file (MP4, WebM…) instead of using a link",
    )
    audio_file = models.FileField(
        upload_to="lessons/audio/", blank=True, null=True,
        help_text="Optional audio version of this lesson (MP3, M4A…)",
    )
    content = models.TextField(blank=True, help_text="Notes shown under the video (supports simple HTML)")
    order = models.PositiveIntegerField(default=0, editable=False)
    is_free_preview = models.BooleanField(default=False, help_text="Non-students can watch this lesson")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        unique_together = [("module", "slug")]

    def __str__(self):
        return f"{self.module.course.title} — {self.title}"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "lesson"
            slug, i = base, 2
            existing = Lesson.objects.filter(module=self.module)
            while existing.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        if not self.order:
            agg = self.module.lessons.aggregate(Max("order"))
            self.order = (agg["order__max"] or 0) + 1
        super().save(*args, **kwargs)

    @property
    def course(self):
        return self.module.course

    @property
    def media_type(self):
        """How the player should present this lesson's main media."""
        if self.video_file:
            return "video_file"
        if self.audio_file:
            return "audio_file"
        if self.video_url:
            return "embed"
        return "none"

    def get_absolute_url(self):
        return reverse("courses:lesson_detail", args=[self.course.slug, self.slug])


class Material(models.Model):
    """Downloadable extra resources attached to a course (PDF, slides, images, zip…)."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="materials")
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="materials/")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]
        unique_together = [("course", "title")]

    def __str__(self):
        return f"{self.course.title} — {self.title}"

    @property
    def ext(self):
        _, _, ext = self.file.name.rpartition(".")
        return ext.lower()

    @property
    def size_kb(self):
        try:
            return max(1, round(self.file.size / 1024))
        except (OSError, AttributeError):
            return None

    @property
    def is_image(self):
        return self.ext in ("png", "jpg", "jpeg", "gif", "webp", "svg")

    @property
    def icon(self):
        icons = {
            "pdf": "📕", "doc": "📘", "docx": "📘", "xls": "📗", "xlsx": "📗",
            "csv": "📊", "zip": "🗜️", "ppt": "📙", "pptx": "📙", "txt": "📄",
        }
        if self.is_image:
            return "🖼️"
        return icons.get(self.ext, "📄")


class Enrollment(models.Model):
    """A student's active access to a course."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    is_active = models.BooleanField(default=False)
    # How the student got in: free enroll, completed Paystack purchase, or admin grant.
    source = models.CharField(
        max_length=20,
        choices=[("free", "Free"), ("paystack", "Paystack"), ("admin", "Admin")],
        default="free",
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]
        unique_together = [("user", "course")]

    def __str__(self):
        return f"{self.user} in {self.course}"


class LessonProgress(models.Model):
    """Marks which lessons a student completed."""

    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="progress")
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="+")
    completed = models.BooleanField(default=True)
    completed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("enrollment", "lesson")]
        ordering = ["lesson__order"]


def enrollment_for(user, course):
    """Active Enrollment for a user+course, or None."""
    if not getattr(user, "is_authenticated", False):
        return None
    return Enrollment.objects.filter(user=user, course=course, is_active=True).first()
