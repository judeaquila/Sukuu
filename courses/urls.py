from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.home, name="home"),
    # Creator dashboard
    path("dashboard/", views.dashboard, name="dashboard"),
    path("create/", views.course_create, name="course_create"),
    path("<slug:slug>/edit/", views.course_update, name="course_update"),
    path("<slug:slug>/delete/", views.course_delete, name="course_delete"),
    path("<slug:slug>/manage/", views.course_manage, name="course_manage"),
    path("<slug:course_slug>/modules/new/", views.module_create, name="module_create"),
    path("<slug:course_slug>/modules/<int:pk>/edit/", views.module_update, name="module_update"),
    path("<slug:course_slug>/modules/<int:pk>/delete/", views.module_delete, name="module_delete"),
    path("<slug:course_slug>/lessons/new/", views.lesson_create, name="lesson_create"),
    path("<slug:course_slug>/lessons/<int:pk>/edit/", views.lesson_update, name="lesson_update"),
    path("<slug:course_slug>/lessons/<int:pk>/delete/", views.lesson_delete, name="lesson_delete"),
    path("<slug:course_slug>/materials/new/", views.material_create, name="material_create"),
    path("<slug:course_slug>/materials/<int:pk>/delete/", views.material_delete, name="material_delete"),
    # Student flow
    path("<slug:slug>/enroll/", views.enroll, name="enroll"),
    path("<slug:course_slug>/lesson/<slug:lesson_slug>/", views.lesson_detail, name="lesson_detail"),
    path(
        "<slug:course_slug>/lesson/<slug:lesson_slug>/toggle/",
        views.lesson_toggle_complete,
        name="lesson_toggle_complete",
    ),
    path("reviews/<int:pk>/feature/", views.review_toggle_feature, name="review_feature"),
    path("<slug:slug>/review/", views.review_submit, name="review_submit"),
    # Course detail last (catches the bare course page)
    path("<slug:slug>/", views.course_detail, name="course_detail"),
]
