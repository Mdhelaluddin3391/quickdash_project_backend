from django.urls import path
from .views import CheckoutView, OrderHistoryView, OrderDetailView
from orders.models import Order, OrderItem, Payment
from .views import (
    CheckoutView, 
    OrderHistoryView, 
    OrderDetailView, 
    PaymentVerificationView,
    OrderCancelView
)
from delivery.models import Delivery

urlpatterns = [

    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('verify-payment/', PaymentVerificationView.as_view(), name='verify-payment'),
    path('', OrderHistoryView.as_view(), name='order-history'),
    path('<str:order_id>/', OrderDetailView.as_view(), name='order-detail'),
    path('<str:order_id>/cancel/', OrderCancelView.as_view(), name='order-cancel'),
    # path('webhook/payment-success/', 
    #      PaymentWebhookView.as_view(), 
    #      name='payment-webhook'),
]