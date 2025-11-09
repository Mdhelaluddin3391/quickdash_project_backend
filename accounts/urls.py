from django.urls import path
from .views import SendOTPView, VerifyOTPView, DeleteAccountView, CustomerProfileView, AddressListCreateView, AddressDetailView, StaffLoginView, UpdateFCMTokenView, StaffPasswordResetRequestView, StaffPasswordResetConfirmView, StaffGoogleLoginView

urlpatterns = [
    # Auth
    path('send-otp/', SendOTPView.as_view(), name='send-otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('staff-login/', StaffLoginView.as_view(), name='staff-login'),
    path('delete/', DeleteAccountView.as_view(), name='delete-account'),
    path('update-fcm-token/', UpdateFCMTokenView.as_view(), name='update-fcm-token'),
    # Profile Management
    path('profile/', CustomerProfileView.as_view(), name='customer-profile'),
    path('staff-google-login/', StaffGoogleLoginView.as_sview(), name='staff-google-login'),
    path(
        'staff-password-reset/', 
        StaffPasswordResetRequestView.as_view(), 
        name='staff-password-reset-request'
    ),
    path(
        'staff-password-reset/confirm/', 
        StaffPasswordResetConfirmView.as_view(), 
        name='staff-password-reset-confirm'
    ),

    # Address Management
    path('addresses/', AddressListCreateView.as_view(), name='address-list-create'),
    path('addresses/<int:pk>/', AddressDetailView.as_view(), name='address-detail'),
    
]