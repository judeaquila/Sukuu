from django.contrib import admin

from .models import Course, Enrollment, Lesson, LessonProgress, Material, Module, Review


class MaterialInline(admin.TabularInline):
    model = Material
    extra = 0
    fields = ("title", "file")


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0
    fields = ("order", "title", "video_url", "is_free_preview")
    show_change_link = True
    readonly_fields = ("order",)


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 0
    fields = ("order", "title")
    show_change_link = True
    readonly_fields = ("order",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "creator", "category", "level", "price", "status", "created")
    list_filter = ("status", "category", "level", "created")
    search_fields = ("title", "summary", "creator__email")
    list_editable = ("status",)
    inlines = [ModuleInline]


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "order")
    search_fields = ("title", "course__title")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "course_name", "module", "order", "is_free_preview")
    search_fields = ("title", "module__course__title")

    @admin.display(description="Course")
    def course_name(self, obj):
        return obj.module.course.title


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "ext", "size_kb", "created")
    search_fields = ("title", "course__title")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "is_active", "source", "created")
    list_filter = ("is_active", "source", "created")
    search_fields = ("user__email", "course__title")


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "lesson", "completed", "completed_at")
    list_filter = ("completed",)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("course", "user", "rating", "is_featured", "created")
    list_filter = ("rating", "is_featured", "created")
    search_fields = ("course__title", "user__email", "body")
    readonly_fields = ("created", "updated")
