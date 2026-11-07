"""Course + lesson + enrolment views.

Creators own their dashboard; students see a classroom-style learning area.
All money movement goes through `payments.paystack`.
"""

import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from payments.models import Transaction
from payments.paystack import PaystackAPI, PaystackInitError

from .forms import CourseForm, LessonForm, MaterialForm, ModuleForm
from .models import Course, Enrollment, Lesson, LessonProgress, Material, Module, enrollment_for

PAGE_SIZE = 12


def home(request):
    """Marketplace landing page: searchable, filterable course catalogue."""
    courses = (
        Course.objects.filter(status=Course.Status.PUBLISHED)
        .select_related("creator")
        .annotate(modules=Count("modules_related", distinct=True))
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
    return render(
        request,
        "courses/course_detail.html",
        {
            "course": course,
            "modules": modules,
            "enrollment": enrollment,
            "is_creator": is_creator,
            "curriculum_unlocked": curriculum_unlocked,
        },
    )


@login_required
def enroll(request, slug):
    """Start the checkout: free = instant access; paid = Paystack hosted checkout."""
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

    # Paid course → create a pending transaction and redirect to Paystack checkout.
    reference = f"OLTSCH-{uuid.uuid4().hex[:12].upper()}"
    with db_transaction.atomic():
        Transaction.objects.create(
            user=request.user,
            course=course,
            reference=reference,
            amount_minor=course.price_minor,
            currency=settings.CURRENCY,
            status=Transaction.Status.PENDING,
        )
    callback_url = request.build_absolute_uri(reverse("payments:callback"))
    try:
        api = PaystackAPI()
        response = api.initialize(
            email=request.user.email,
            amount_minor=course.price_minor,
            reference=reference,
            callback_url=callback_url,
            metadata={
                "course_id": course.id,
                "course_title": course.title,
                "user_id": request.user.id,
                "custom_fields": [
                    {"display_name": "Course", "variable_name": "course", "value": course.title}
                ],
            },
        )
    except PaystackInitError as exc:
        Transaction.objects.filter(reference=reference).update(
            status=Transaction.Status.FAILED, raw_response=str(exc)
        )
        messages.error(request, f"Payment could not be started: {exc}")
        return redirect("courses:course_detail", course.slug)

    url = response.get("data", {}).get("authorization_url")
    Transaction.objects.filter(reference=reference).update(raw_response=response)
    if not url:
        messages.error(request, "Payment could not be started. Please try again.")
        return redirect("courses:course_detail", course.slug)
    return redirect(url)


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
    """Creator home: their courses, sales stats and earnings."""
    courses = request.user.courses.all().order_by("-created")
    txs = Transaction.objects.filter(course__in=courses, status=Transaction.Status.SUCCESS)
    gross_minor = sum(t.amount_minor for t in txs)
    fees_minor = sum(t.platform_fee_minor for t in txs)
    return render(
        request,
        "courses/dashboard.html",
        {
            "courses": courses,
            "total_students": Enrollment.objects.filter(course__in=courses, is_active=True).count(),
            "gross_minor": gross_minor,
            "fees_minor": fees_minor,
            "earnings_minor": gross_minor - fees_minor,
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
    return render(
        request,
        "courses/course_manage.html",
        {
            "course": course,
            "modules": modules,
            "students": enroll_students,
            "txs_by_reference": txs_by_reference,
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
