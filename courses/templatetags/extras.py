"""Custom template filters for the online school."""

import re
from urllib.parse import urlparse, parse_qs

from django import template
from django.conf import settings

register = template.Library()


@register.filter
def ghs(amount):
    """Format an amount as platfrom currency, e.g. GH₵120.00."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return amount
    if value == 0:
        return "Free"
    return f"{settings.CURRENCY_SYMBOL}{value:,.2f}"


@register.filter
def pesewas(amount_minor):
    """Format an amount stored in minor units (pesewas) as currency, e.g. GH₵150.00."""
    try:
        value = int(amount_minor) / 100
    except (TypeError, ValueError):
        return amount_minor
    return f"{settings.CURRENCY_SYMBOL}{value:,.2f}"


_YT_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{6,})"
)
_VIMEO_RE = re.compile(r"vimeo\.com/(\d+)")


@register.filter
def embed_url(video_url):
    """Convert a YouTube/Vimeo/MP4 URL to something playable in an iframe/video tag."""
    if not video_url:
        return ""
    match = _YT_RE.search(video_url)
    if match:
        start = parse_qs(urlparse(video_url).query).get("t", ["0"])[0]
        seconds = re.sub(r"[^\d]", "", start) or "0"
        return f"https://www.youtube.com/embed/{match.group(1)}?start={seconds}&rel=0"
    match = _VIMEO_RE.search(video_url)
    if match:
        return f"https://player.vimeo.com/video/{match.group(1)}"
    return video_url  # direct MP4 / other


@register.filter
def star_string(value):
    """Turn a rating into star glyphs, e.g. 4.6 → '★★★★☆' (rounds to nearest)."""
    try:
        rating = float(value)
    except (TypeError, ValueError):
        rating = 0.0
    full = max(0, min(5, int(round(rating))))
    return "★" * full + "☆" * (5 - full)


@register.simple_tag
def commission_rate():
    return settings.PLATFORM_COMMISSION_PERCENT
