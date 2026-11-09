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
    path("checkout/course/<slug:slug>/", views.course_checkout, name="course_checkout"),
    path("webhook/", views.webhook, name="webhook"),
    path("payouts/", views.payouts, name="payouts"),
    path("payouts/verify-account/", views.payout_account_verify, name="payout_account_verify"),
    path("payouts/accounts/<int:pk>/remove/", views.payout_account_delete, name="payout_account_delete"),
    path("payouts/requests/<int:pk>/cancel/", views.payout_request_cancel, name="payout_request_cancel"),
    path("coupons/", views.coupons, name="coupons"),
    path("coupons/<int:pk>/delete/", views.coupon_delete, name="coupon_delete"),
]
