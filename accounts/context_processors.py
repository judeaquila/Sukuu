from django.conf import settings


def platform_settings(request):
    """Expose platform business settings to templates."""
    return {
        "CURRENCY": settings.CURRENCY,
        "CURRENCY_SYMBOL": settings.CURRENCY_SYMBOL,
        "COMMISSION_PERCENT": settings.PLATFORM_COMMISSION_PERCENT,
    }
