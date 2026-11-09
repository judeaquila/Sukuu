"""Sitemaps for LearnSasa: published courses plus the static entry pages."""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from courses.models import Course


class StaticViewSitemap(Sitemap):
    priority = 0.6
    changefreq = "monthly"

    def items(self):
        return ["/", "/privacy/", "/terms-of-service/"]

    def location(self, item):
        return item


class CourseSitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"

    def items(self):
        return Course.objects.filter(status=Course.Status.PUBLISHED)

    def lastmod(self, obj):
        return obj.updated

    def location(self, obj):
        return obj.get_absolute_url()


SITEMAPS = {"static": StaticViewSitemap, "courses": CourseSitemap}
