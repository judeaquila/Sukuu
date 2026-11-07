from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("signup/", views.signup, name="signup"),
    path("login/", views.user_login, name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("learning/", views.my_learning, name="my_learning"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("creator/<str:username>/", views.creator_public, name="creator_public"),
]
