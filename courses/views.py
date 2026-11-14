"""Course + lesson + enrolment views.

Creators own their dashboard; students see a classroom-style learning area.
All money movement goes through `payments.paystack`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from payments.models import Transaction
from payments.services import payout_summary

from .forms import CourseForm, LessonForm, MaterialForm, ModuleForm
from .models import Course, Enrollment, Lesson, LessonProgress, Material, Module, Review, enrollment_for
from .templatetags.extras import span_text

PAGE_SIZE = 12


def home(request):
    """Marketplace landing page: searchable, filterable course catalogue."""
    courses = (
        Course.objects.filter(status=Course.Status.PUBLISHED)
        .select_related("creator")
        .annotate(
            modules=Count("modules_related", distinct=True),
            reviews_avg=Avg("reviews__rating"),
            reviews_count=Count("reviews", distinct=True),
        )
    )
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    if query:
        courses = courses.filter(Q(title__icontains=query) | Q(summary__icontains=query))
    if category:
        courses = courses.filter(category=category)
    courses = courses.order_by("-created")

    paginator = Paginator(courses, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "courses/home.html",
        {
            "page_obj": page_obj,
            "query": query,
            "category": category,
            "total_published": paginator.count,
            "top_categories": [
                {"value": value, "label": label}
                for value, label in Course.Category.choices
            ],
        },
    )


def _course_or_404(slug, *, published_only=True):
    qs = Course.objects.select_related()
    if published_only:
        qs = qs.filter(status=Course.Status.PUBLISHED)
    return get_object_or_404(qs, slug=slug)


def course_detail(request, slug):
    course = _course_or_404(slug)
    user = request.user
    is_creator = user.is_authenticated and (
        user == course.creator or user.is_staff
    )
    enrollment = enrollment_for(user, course)
    modules = course.modules_related.prefetch_related("lessons")
    curriculum_unlocked = is_creator or bool(enrollment)

    # Curriculum stats: per-module lesson count + media time, course totals
    curriculum = []
    total_lessons = 0
    total_seconds = 0
    for module in modules:
        lessons = list(module.lessons.all())
        seconds = sum(l.duration_seconds or 0 for l in lessons)
        total_lessons += len(lessons)
        total_seconds += seconds
        curriculum.append(
            {
                "module": module,
                "lessons": lessons,
                "count": len(lessons),
                "seconds": seconds,
                "span": span_text(seconds),
            }
        )
    materials_count = course.materials.count()

    # Reviews: creator-pinned first, then newest
    featured = course.reviews.filter(is_featured=True).select_related("user")
    others = course.reviews.filter(is_featured=False).order_by("-created").select_related("user")
    rating_avg, rating_count = course.rating_stats

    my_review = None
    if enrollment:
        my_review = course.reviews.filter(user=user).first()

    # Creator snapshot + more of their courses
    creator = course.creator
    creator_profile = getattr(creator, "creator_profile", None)
    more_by_creator = list(
        Course.objects.filter(status=Course.Status.PUBLISHED, creator=creator)
        .exclude(pk=course.pk)
        .select_related("creator")
        .annotate(reviews_avg=Avg("reviews__rating"), reviews_count=Count("reviews", distinct=True))
        .order_by("-created")[:3]
    )
    similar_courses = (
        Course.objects.filter(status=Course.Status.PUBLISHED, category=course.category)
        .exclude(pk__in=[course.pk, *[c.pk for c in more_by_creator]])
        .select_related("creator")
        .annotate(reviews_avg=Avg("reviews__rating"), reviews_count=Count("reviews", distinct=True))
        .order_by("-reviews_count", "-created")[:3]
    )
    creator_published_count = Course.objects.filter(
        status=Course.Status.PUBLISHED, creator=creator
    ).count()
    creator_students = Enrollment.objects.filter(
        course__creator=creator, is_active=True
    ).values("user").distinct().count()

    return render(
        request,
        "courses/course_detail.html",
        {
            "course": course,
            "modules": modules,
            "enrollment": enrollment,
            "is_creator": is_creator,
            "curriculum_unlocked": curriculum_unlocked,
            "curriculum": curriculum,
            "total_lessons": total_lessons,
            "total_seconds": total_seconds,
            "materials_count": materials_count,
            "all_reviews": list(featured) + list(others),
            "rating_avg": rating_avg,
            "rating_count": rating_count,
            "my_review": my_review,
            "now": timezone.now(),
            "creator": creator,
            "creator_profile": creator_profile,
            "more_by_creator": more_by_creator,
            "similar_courses": similar_courses,
            "creator_published_count": creator_published_count,
            "creator_students": creator_students,
        },
    )


@login_required
@require_POST
def review_submit(request, slug):
    """Enrolled students rate/review a course; resubmitting replaces their review."""
    course = _course_or_404(slug)
    if request.user == course.creator and not request.user.is_staff:
        messages.warning(request, "Creators can't review their own course.")
        return redirect("courses:course_detail", course.slug)
    if not enrollment_for(request.user, course):
        messages.warning(request, "Only enrolled students can review a course.")
        return redirect("courses:course_detail", course.slug)

    try:
        rating = int(request.POST.get("rating", ""))
    except ValueError:
        rating = 0
    if rating not in (1, 2, 3, 4, 5):
        messages.error(request, "Pick a star rating before submitting your review.")
        return redirect(f"{reverse('courses:course_detail', args=[course.slug])}#reviews")

    body = (request.POST.get("body") or "").strip()[:2000]
    review, created = Review.objects.update_or_create(
        course=course, user=request.user, defaults={"rating": rating, "body": body}
    )

    # Mirror the review into the course's community feed; editing the review
    # updates the same post so the feed never accumulates duplicates.
    from community.models import Community, Post as CommunityPost

    community_obj, _ = Community.objects.get_or_create(
        course=course,
        defaults={"name": f"{course.title} — Community", "description": course.summary},
    )
    stars = "★" * rating + "☆" * (5 - rating)
    CommunityPost.objects.update_or_create(
        community=community_obj,
        review=review,
        defaults={
            "author": request.user,
            "title": f"⭐ {rating}-star review",
            "body": (
                f"Rated this course {stars} ({rating}/5)\n\n"
                f"{review.body or 'No written comment — just the stars.'}"
            ),
        },
    )

    messages.success(request, f"Review {'posted' if created else 'updated'} — thank you! It's now in the course community too.")
    return redirect(f"{reverse('courses:course_detail', args=[course.slug])}#reviews")


@login_required
@require_POST
def review_toggle_feature(request, pk):
    """Creator pins/unpins a review on their course's page."""
    review = get_object_or_404(
        Review.objects.select_related("course"), pk=pk, course__creator=request.user
    )
    review.is_featured = not review.is_featured
    review.save(update_fields=["is_featured"])
    messages.info(
        request,
        f"Review {'featured on your course page' if review.is_featured else 'unfeatured — it still shows in the list'}'.",
    )
    return redirect("courses:course_manage", review.course.slug)


@login_required
def enroll(request, slug):
    """Free courses = instant access; paid = Paystack inline modal (guests too)."""
    from payments.views import course_checkout

    course = _course_or_404(slug)
    enrollment = enrollment_for(request.user, course)
    if enrollment:
        messages.info(request, "You are already enrolled in this course.")
        return redirect("accounts:my_learning")

    if course.is_free:
        Enrollment.objects.get_or_create(
            user=request.user,
            course=course,
            defaults={"is_active": True, "source": "free"},
        )
        messages.success(request, f"You now have access to \u201c{course.title}\u201d. Enjoy!")
        first_lesson = course.modules_related.first().lessons.first() if course.modules_related.exists() else None
        if first_lesson:
            return redirect(first_lesson.get_absolute_url())
        return redirect("courses:course_detail", course.slug)

    # Paid course → the guest-friendly checkout with the inline payment modal.
    return course_checkout(request, slug)


# ---------------------------------------------------------------------------
# Lesson player (student classroom)
# ---------------------------------------------------------------------------


def _lesson_access(request, course, lesson, enrollment, is_creator):
    return is_creator or bool(enrollment) or lesson.is_free_preview


def lesson_detail(request, course_slug, lesson_slug):
    course = _course_or_404(course_slug)
    modules = course.modules_related.prefetch_related("lessons")
    lessons = [l for module in modules for l in module.lessons.all()]
    try:
        lesson_index = next(i for i, l in enumerate(lessons) if l.slug == lesson_slug)
    except StopIteration:
        raise Http404("Lesson not found.")
    lesson = lessons[lesson_index]
    user = request.user
    is_creator = user.is_authenticated and (user == course.creator or user.is_staff)
    enrollment = enrollment_for(user, course)
    if not _lesson_access(request, course, lesson, enrollment, is_creator):
        if user.is_authenticated:
            messages.info(request, "Enroll to unlock this lesson.")
            return redirect("courses:course_detail", course.slug)
        return redirect(f"{reverse('accounts:login')}?next={lesson.get_absolute_url()}")

    siblings = lessons

    completed_slugs = set()
    progress = None
    if enrollment:
        progress = LessonProgress.objects.filter(enrollment=enrollment, lesson__in=siblings, completed=True)
        completed_slugs = set(progress.values_list("lesson__slug", flat=True))
    return render(
        request,
        "courses/lesson_detail.html",
        {
            "course": course,
            "modules": modules,
            "lesson": lesson,
            "prev_lesson": siblings[lesson_index - 1] if lesson_index else None,
            "next_lesson": siblings[lesson_index + 1] if lesson_index < len(siblings) - 1 else None,
            "enrollment": enrollment,
            "completed_slugs": completed_slugs,
            "is_creator": is_creator,
        },
    )


@login_required
def lesson_toggle_complete(request, course_slug, lesson_slug):
    if request.method != "POST":
        return redirect("courses:course_detail", course_slug)
    course = get_object_or_404(Course, slug=course_slug, status=Course.Status.PUBLISHED)
    enrollment = enrollment_for(request.user, course)
    if not enrollment:
        messages.warning(request, "Enroll first to track your progress.")
        return redirect("courses:course_detail", course.slug)
    lesson = get_object_or_404(Lesson, module__course=course, slug=lesson_slug)
    progress, created = LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
    if created:
        progress.completed = True
    else:
        progress.completed = not progress.completed
    progress.save()
    return redirect("courses:lesson_detail", course.slug, lesson_slug)


# ---------------------------------------------------------------------------
# Creator dashboard
# ---------------------------------------------------------------------------


def _own_course(user, slug):
    if not user.is_authenticated:
        raise Http404()
    course = get_object_or_404(Course.objects.select_related(), slug=slug, creator=user)
    return course


@login_required
def dashboard(request):
    """Creator home: their courses, sales stats, earnings and student reviews."""
    courses = request.user.courses.all().order_by("-created")
    txs = Transaction.objects.filter(course__in=courses, status=Transaction.Status.SUCCESS)
    gross_minor = sum(t.amount_minor for t in txs)
    fees_minor = sum(t.platform_fee_minor for t in txs)

    review_stats = Review.objects.filter(course__creator=request.user).aggregate(
        avg=Avg("rating"), count=Count("id")
    )
    latest_reviews = (
        Review.objects.filter(course__creator=request.user)
        .select_related("course", "user")
        .order_by("-created")[:6]
    )
    return render(
        request,
        "courses/dashboard.html",
        {
            "courses": courses,
            "total_students": Enrollment.objects.filter(course__in=courses, is_active=True).count(),
            "gross_minor": gross_minor,
            "fees_minor": fees_minor,
            "earnings_minor": gross_minor - fees_minor,
            "payout_summary": payout_summary(request.user),
            "latest_reviews": latest_reviews,
            "review_avg": (round(review_stats["avg"], 1) if review_stats["count"] else None),
            "review_count": review_stats["count"],
        },
    )


@login_required
def course_create(request):
    form = CourseForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        course = form.save(commit=False)
        course.creator = request.user
        course.save()
        messages.success(request, "Course created! Add modules and lessons next.")
        return redirect("courses:course_manage", course.slug)
    return render(request, "courses/course_form.html", {"form": form, "title": "Create a course"})


@login_required
def course_update(request, slug):
    course = _own_course(request.user, slug)
    form = CourseForm(request.POST or None, request.FILES or None, instance=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Course updated.")
        return redirect("courses:course_manage", course.slug)
    return render(request, "courses/course_form.html", {"form": form, "course": course, "title": f"Edit — {course.title}"})


@login_required
def course_delete(request, slug):
    course = _own_course(request.user, slug)
    if request.method == "POST":
        title = course.title
        course.delete()
        messages.info(request, f"Course “{title}” deleted.")
        return redirect("courses:dashboard")
    return render(request, "courses/course_delete.html", {"course": course})


@login_required
def course_manage(request, slug):
    """Curriculum builder: reorder-free list of modules & lessons with add links."""
    course = _own_course(request.user, slug)
    modules = course.modules_related.prefetch_related("lessons")
    enroll_students = Enrollment.objects.filter(course=course, is_active=True).select_related("user")[:10]
    txs_by_reference = {
        t.reference: t for t in Transaction.objects.filter(course=course, status=Transaction.Status.SUCCESS)
    }
    rating_avg, rating_count = course.rating_stats
    return render(
        request,
        "courses/course_manage.html",
        {
            "course": course,
            "modules": modules,
            "students": enroll_students,
            "txs_by_reference": txs_by_reference,
            "course_reviews": course.reviews.select_related("user").order_by("-created"),
            "rating_avg": rating_avg,
            "rating_count": rating_count,
        },
    )


@login_required
def module_create(request, course_slug):
    course = _own_course(request.user, course_slug)
    form = ModuleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        module = form.save(commit=False)
        module.course = course
        module.save()
        messages.success(request, "Module added.")
        return redirect("courses:course_manage", course.slug)
    return render(request, "courses/module_form.html", {"form": form, "course": course})


@login_required
def module_update(request, course_slug, pk):
    course = _own_course(request.user, course_slug)
    module = get_object_or_404(Module, course=course, pk=pk)
    form = ModuleForm(request.POST or None, instance=module)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Module updated.")
        return redirect("courses:course_manage", course.slug)
    return render(
        request,
        "courses/module_form.html",
        {"form": form, "course": course, "module": module, "title": f"Edit module — {module.title}"},
    )


@login_required
def module_delete(request, course_slug, pk):
    course = _own_course(request.user, course_slug)
    module = get_object_or_404(Module, course=course, pk=pk)
    if request.method == "POST":
        title = module.title
        module.delete()
        messages.info(request, f"Module “{title}” deleted.")
        return redirect("courses:course_manage", course.slug)
    return render(request, "courses/module_delete.html", {"course": course, "module": module})


@login_required
def lesson_create(request, course_slug):
    course = _own_course(request.user, course_slug)
    form = LessonForm(request.POST or None, request.FILES or None, course=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Lesson added.")
        return redirect("courses:course_manage", course.slug)
    return render(request, "courses/lesson_form.html", {"form": form, "course": course})


@login_required
def lesson_update(request, course_slug, pk):
    course = _own_course(request.user, course_slug)
    lesson = get_object_or_404(Lesson, module__course=course, pk=pk)
    form = LessonForm(request.POST or None, request.FILES or None, instance=lesson, course=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Lesson updated.")
        return redirect("courses:course_manage", course.slug)
    return render(
        request,
        "courses/lesson_form.html",
        {"form": form, "course": course, "lesson": lesson, "title": f"Edit lesson — {lesson.title}"},
    )


@login_required
def lesson_delete(request, course_slug, pk):
    course = _own_course(request.user, course_slug)
    lesson = get_object_or_404(Lesson, module__course=course, pk=pk)
    if request.method == "POST":
        title = lesson.title
        lesson.delete()
        messages.info(request, f"Lesson “{title}” deleted.")
        return redirect("courses:course_manage", course.slug)
    return render(request, "courses/lesson_delete.html", {"course": course, "lesson": lesson})


@login_required
def material_create(request, course_slug):
    course = _own_course(request.user, course_slug)
    form = MaterialForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        material = form.save(commit=False)
        material.course = course
        material.save()
        messages.success(request, "Material uploaded.")
        return redirect("courses:course_manage", course.slug)
    return render(request, "courses/material_form.html", {"form": form, "course": course})


@login_required
def material_delete(request, course_slug, pk):
    if request.method != "POST":
        return redirect("courses:dashboard")
    course = _own_course(request.user, course_slug)
    material = get_object_or_404(Material, course=course, pk=pk)
    material.delete()
    messages.info(request, f"Material “{material.title}” removed.")
    return redirect("courses:course_manage", course.slug)
