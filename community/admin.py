from django.contrib import admin

from .models import Comment, Community, Post


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ("author", "body", "created")


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "created")
    search_fields = ("name", "course__title")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "community", "is_pinned", "created")
    list_filter = ("is_pinned", "created")
    search_fields = ("title", "body", "author__email")
    inlines = [CommentInline]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("author", "post", "created")
    search_fields = ("body", "author__email")
