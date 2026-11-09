"""
URL configuration for schoolcore project.

The root of the site is the course marketplace; each Django app owns its
own section under a namespace.
"""

from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps import views as sitemap_views
from django.http import HttpResponse
from django.urls import include, path
from django.urls import reverse
from django.views.generic import TemplateView

from courses import views as course_views
from .sitemaps import SITEMAPS


def robots_txt(request):
    sitemap_url = request.build_absolute_uri(reverse("django.contrib.sitemaps.views.sitemap"))
    return HttpResponse(
        "User-Agent: *\nAllow: /\nDisallow: /admin/\n"
        f"Sitemap: {sitemap_url}\n",
        content_type="text/plain",
    )


urlpatterns = [
    path("", course_views.home, name="home"),
    path("privacy/", TemplateView.as_view(template_name="pages/privacy.html"), name="privacy"),
    path("terms-of-service/", TemplateView.as_view(template_name="pages/terms.html"), name="terms"),
    path("robots.txt", robots_txt, name="robots"),
    path("sitemap.xml", sitemap_views.sitemap, {"sitemaps": SITEMAPS}, name="django.contrib.sitemaps.views.sitemap"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("courses/", include("courses.urls")),
    path("community/", include("community.urls")),
    path("payments/", include("payments.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Friendlier admin branding
admin.site.site_header = "LearnSasa Admin (Ghana)"
admin.site.site_title = "LearnSasa Admin"
admin.site.index_title = "Platform management"
