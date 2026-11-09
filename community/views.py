import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from courses.models import enrollment_for

from .forms import CommentForm, PostForm
from .models import Community, Post

logger = logging.getLogger(__name__)

PERMISSION_DENIED = "Enroll in the course to join the community."


def _access(request, course_slug, community=None):
    """Return (course, community, is_creator) or None when user can't enter."""
    from courses.models import Course

    if not request.user.is_authenticated:
        return None
    course = get_object_or_404(Course, slug=course_slug)
    is_creator = request.user == course.creator or request.user.is_staff
    enrollment = enrollment_for(request.user, course)
    if not (is_creator or enrollment):
        return None
    if community is None:
        community = Community.objects.filter(course=course).first()
        if community is None:
            community = Community.objects.create(
                course=course,
                name=f"{course.title} — Community",
                description=course.summary,
            )
    return course, community, is_creator


def _denied(request, course_slug):
    messages.info(request, PERMISSION_DENIED)
    return redirect("courses:course_detail", course_slug)


def community(request, course_slug):
    access = _access(request, course_slug)
    if access is None:
        return _denied(request, course_slug)
    course, community, is_creator = access
    posts = community.posts.select_related("author", "review").prefetch_related("comments__author")
    return render(
        request,
        "community/community.html",
        {
            "course": course,
            "community": community,
            "posts": posts,
            "post_form": PostForm(),
            "is_creator": is_creator,
        },
    )


def post_detail(request, course_slug, post_id):
    access = _access(request, course_slug)
    if access is None:
        return _denied(request, course_slug)
    course, community, is_creator = access
    post = get_object_or_404(Post, community=community, pk=post_id)
    return render(
        request,
        "community/post_detail.html",
        {
            "course": course,
            "community": community,
            "post": post,
            "comments": post.comments.select_related("author"),
            "comment_form": CommentForm(),
            "is_creator": is_creator,
            "liked": request.user in post.likes.all(),
            "review": post.review,
        },
    )


@login_required
def post_create(request, course_slug):
    access = _access(request, course_slug)
    if access is None:
        return _denied(request, course_slug)
    course, community, is_creator = access
    if request.method != "POST":
        return redirect("community:community", course.slug)
    form = PostForm(request.POST)
    new_post = None
    if form.is_valid():
        new_post = form.save(commit=False)
        new_post.community = community
        new_post.author = request.user
        new_post.save()
        messages.success(request, "Posted!")
        return redirect("community:post_detail", course.slug, new_post.id)
    return redirect("community:community", course.slug)


@login_required
def post_toggle_like(request, course_slug, post_id):
    access = _access(request, course_slug)
    if access is None:
        return _denied(request, course_slug)
    course, community, is_creator = access
    post = get_object_or_404(Post, community=community, pk=post_id)
    if request.user in post.likes.all():
        post.likes.remove(request.user)
    else:
        post.likes.add(request.user)
    return redirect("community:post_detail", course.slug, post.id)


@login_required
def post_toggle_pin(request, course_slug, post_id):
    """Only the course creator can pin/unpin posts."""
    access = _access(request, course_slug)
    if access is None or not access[2]:
        return _denied(request, course_slug)
    course, community, is_creator = access
    post = get_object_or_404(Post, community=community, pk=post_id)
    post.is_pinned = not post.is_pinned
    post.save(update_fields=["is_pinned"])
    return redirect("community:post_detail", course.slug, post.id)


@login_required
def comment_create(request, course_slug, post_id):
    access = _access(request, course_slug)
    if access is None:
        return _denied(request, course_slug)
    course, community, is_creator = access
    post = get_object_or_404(Post, community=community, pk=post_id)
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.post = post
            comment.author = request.user
            comment.save()
    return redirect("community:post_detail", course.slug, post.id)
