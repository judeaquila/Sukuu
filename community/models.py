from django.conf import settings
from django.db import models

from courses.models import Course


class Community(models.Model):
    """Every course gets a private community. Only enrolled students and the
    course creator can view it and post."""

    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name="community")
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=250, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Post(models.Model):
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")
    title = models.CharField(max_length=200)
    body = models.TextField()
    is_pinned = models.BooleanField(default=False, help_text="Course creator can pin to the top")
    likes = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="liked_posts")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_pinned", "-created"]

    def __str__(self):
        return self.title

    @property
    def like_count(self):
        return self.likes.count()


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    body = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]

    def __str__(self):
        return f"{self.author} on {self.post.title}"
