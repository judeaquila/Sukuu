"""
URL configuration for schoolcore project.

The root of the site is the course marketplace; each Django app owns its
own section under a namespace.
"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from courses import views as course_views

urlpatterns = [
    path("", course_views.home, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("courses/", include("courses.urls")),
    path("community/", include("community.urls")),
    path("payments/", include("payments.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Friendlier admin branding
admin.site.site_header = "Online School Admin (Ghana)"
admin.site.site_title = "Online School Admin"
admin.site.index_title = "Platform management"
