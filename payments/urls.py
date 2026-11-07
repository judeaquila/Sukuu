from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("callback/", views.callback, name="callback"),
    path(
        "checkout/<str:reference>/",
        views.checkout_pending,
        name="checkout_pending",
    ),
    path("webhook/", views.webhook, name="webhook"),
    path("payouts/", views.payouts, name="payouts"),
    path("payouts/accounts/<int:pk>/remove/", views.payout_account_delete, name="payout_account_delete"),
]
