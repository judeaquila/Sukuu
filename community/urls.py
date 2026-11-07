from django.urls import path

from . import views

app_name = "community"

urlpatterns = [
    path("<slug:course_slug>/", views.community, name="community"),
    path("<slug:course_slug>/new/", views.post_create, name="post_create"),
    path("<slug:course_slug>/post/<int:post_id>/", views.post_detail, name="post_detail"),
    path("<slug:course_slug>/post/<int:post_id>/pin/", views.post_toggle_pin, name="post_toggle_pin"),
    path("<slug:course_slug>/post/<int:post_id>/like/", views.post_toggle_like, name="post_toggle_like"),
    path("<slug:course_slug>/post/<int:post_id>/comments/", views.comment_create, name="comment_create"),
]
