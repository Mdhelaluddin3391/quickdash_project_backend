from django.urls import path
from .views import (
    RiderProfileView,
    RiderLocationUpdateView,
    AvailableDeliveryListView,
    AcceptDeliveryView,
    UpdateDeliveryStatusView,
    CurrentDeliveryDetailView,
    StaffNewOrderListView,
    StaffUpdateOrderStatusView,
    RiderEarningsView,
    RiderCashDepositView
)

urlpatterns = [
    path('profile/', RiderProfileView.as_view(), name='rider-profile'),
    
    path('profile/update-location/', 
         RiderLocationUpdateView.as_view(), 
         name='rider-update-location'),
    
    path('available/', 
         AvailableDeliveryListView.as_view(), 
         name='available-deliveries'),
    
    path('current/', 
         CurrentDeliveryDetailView.as_view(), 
         name='current-delivery'),

    path('<int:pk>/accept/', 
         AcceptDeliveryView.as_view(), 
         name='accept-delivery'),
    
    path('<int:pk>/update-status/', 
         UpdateDeliveryStatusView.as_view(), 
         name='update-delivery-status'),


     path('staff/new-orders/', 
         StaffNewOrderListView.as_view(), 
         name='staff-new-orders'),

     path('earnings/', 
         RiderEarningsView.as_view(), 
         name='rider-earnings'),
    

    path('staff/order/<str:order_id>/update-status/',
         StaffUpdateOrderStatusView.as_view(),
         name='staff-update-order'),

     path('deposit-cash/', 
         RiderCashDepositView.as_view(), 
         name='rider-deposit-cash'),
]