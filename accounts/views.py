# quickdash_project_backend/accounts/views.py

import logging
import random
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

# Model Imports
from .models import User, Address, CustomerProfile
from delivery.models import RiderProfile # Rider model import
# (Delivery aur PickTask imports ko runtime par guard kiya gaya hai)

# Serializer Imports
from .serializers import (
    OTPSerializer, 
    OTPVerifySerializer, 
    AddressSerializer, 
    CustomerProfileSerializer,
    StaffLoginSerializer,
    FCMTokenSerializer,
    StaffPasswordResetRequestSerializer,
    StaffPasswordResetConfirmSerializer,
    StaffGoogleLoginSerializer,
    StaffOTPVerifySerializer
)

# Permission Imports
from .permissions import IsCustomer 

# Task Imports
from .tasks import send_otp_sms_task

# Setup logger
logger = logging.getLogger(__name__)


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

# =======================================
# === CUSTOMER AUTH (Phone + OTP) ===
# =======================================

class SendOTPView(generics.GenericAPIView):
    serializer_class = OTPSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data['phone_number']

        otp = random.randint(100000, 999999)
        send_otp_sms_task.delay(phone_number, otp)

        # Customer ke liye 'otp_' key
        cache.set(f"otp_{phone_number}", otp, timeout=300) 

        return Response({"success": "OTP sent successfully."}, status=status.HTTP_200_OK)


class VerifyOTPView(generics.GenericAPIView):
    serializer_class = OTPVerifySerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        otp = int(serializer.validated_data['otp']) 

        # Customer ki 'otp_' key check karein
        session_otp = cache.get(f"otp_{phone_number}") 

        if session_otp is None or otp != session_otp:
            return Response({"error": "Invalid or Expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        # Customer ke liye get_or_create (taaki naya customer ban sake)
        user, created = User.objects.get_or_create(
            phone_number=phone_number,
            defaults={'username': phone_number} 
        )

        if created:
            logger.info(f"New user created: {user.username}")
        else:
            logger.info(f"User logged in: {user.username}")

        tokens = get_tokens_for_user(user)
        cache.delete(f"otp_{phone_number}")
  
        return Response(tokens, status=status.HTTP_200_OK)

# =======================================
# === RIDER AUTH (Phone + OTP) ===
# =======================================

class RiderSendOTPView(generics.GenericAPIView):
    """
    Naya View: Sirf Riders ke liye OTP bhejta hai.
    """
    serializer_class = OTPSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data['phone_number']
        
        # --- OPTIMIZED LOGIC ---
        try:
            # Check karein ki user hai AUR uske paas RiderProfile hai
            user = User.objects.get(phone_number=phone_number, rider_profile__isnull=False)
        except User.DoesNotExist:
            return Response({"error": "Is number se koi Rider account register nahi hai."}, status=status.HTTP_404_NOT_FOUND)
        # --- END OPTIMIZED LOGIC ---

        otp = random.randint(100000, 999999)
        send_otp_sms_task.delay(phone_number, otp)
        
        # Rider ke liye alag 'rider_otp_' key
        cache.set(f"rider_otp_{phone_number}", otp, timeout=300) 

        return Response({"success": "Rider OTP sent successfully."}, status=status.HTTP_200_OK)


class RiderVerifyOTPView(generics.GenericAPIView):
    """
    Naya View: Sirf Riders ke liye OTP verify karta hai.
    """
    serializer_class = OTPVerifySerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        otp = int(serializer.validated_data['otp']) 

        # Rider ki 'rider_otp_' key check karein
        session_otp = cache.get(f"rider_otp_{phone_number}") 

        if session_otp is None or otp != session_otp:
            return Response({"error": "Invalid or Expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        # --- NAYA LOGIC ---
        try:
            # Sirf 'get' karein, 'get_or_create' nahi
            user = User.objects.get(phone_number=phone_number, rider_profile__isnull=False)
        except User.DoesNotExist:
            return Response({"error": "Rider account not found."}, status=status.HTTP_404_NOT_FOUND)
        # --- END NAYA LOGIC ---

        tokens = get_tokens_for_user(user)
        cache.delete(f"rider_otp_{phone_number}")
  
        # Role bhi bhej dein
        return Response({
            'tokens': tokens,
            'role': 'rider',
            'user_id': user.id
        }, status=status.HTTP_200_OK)

# =======================================
# === STAFF/MANAGER AUTH ===
# =======================================

class StaffLoginView(generics.GenericAPIView):
    """
    (UPDATED)
    Sirf Store Staff ke (Phone + Password) Login ke liye.
    """
    serializer_class = StaffLoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        tokens = get_tokens_for_user(user)
        
        # --- YEH BADLAAV HAI ---
        # Ab yeh view hamesha 'staff' hi return karega
        role = "staff"
        # --- BADLAAV KHATAM ---

        return Response({
            'tokens': tokens,
            'role': role,
            'user_id': user.id
        }, status=status.HTTP_200_OK)


class StaffGoogleLoginView(generics.GenericAPIView):
    """
    API: POST /api/accounts/staff-google-login/
    Google 'id_token' ko verify karta hai aur staff ke liye login karta hai.
    """
    serializer_class = StaffGoogleLoginSerializer
    permission_classes = [permissions.AllowAny]

    COMPANY_DOMAIN = getattr(settings, 'COMPANY_GOOGLE_DOMAIN', 'Qickdash.com')
    GOOGLE_CLIENT_ID = getattr(settings, 'GOOGLE_STAFF_CLIENT_ID', None)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        token = serializer.validated_data['id_token']

        if not self.GOOGLE_CLIENT_ID:
            return Response(
                {"error": "Google login is not configured on the server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        try:
            # ... (poora Google logic waisa hi rahega) ...
            id_info = id_token.verify_oauth2_token(
                token, 
                google_requests.Request(), 
                self.GOOGLE_CLIENT_ID
            )
            email = id_info.get('email')
            # ... (domain check logic waisa hi rahega) ...
            try:
                domain = email.split('@')[1]
                if domain.lower() != self.COMPANY_DOMAIN.lower():
                    return Response(
                        {"error": f"Aap sirf '{self.COMPANY_DOMAIN}' email se hi login kar sakte hain."},
                        status=status.HTTP_403_FORBIDDEN
                    )
            except Exception:
                 return Response(
                    {"error": "Invalid email format."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            username = email.split('@')[0]
            
            user, created = User.objects.get_or_create(
                email__iexact=email,
                defaults={
                    'username': username,
                    'email': email,
                    'first_name': id_info.get('given_name', ''),
                    'last_name': id_info.get('family_name', ''),
                    'phone_number': None
                }
            )
            
            # --- YEH BADLAAV HAI ---
            # Ab hum sirf 'store_staff_profile' check karenge
            if not hasattr(user, 'store_staff_profile'):
                return Response(
                    {"error": "Aapka company account register hai, lekin staff portal ke liye authorized nahi hai. Please admin se contact karein."},
                    status=status.HTTP_403_FORBIDDEN
                )
            # --- BADLAAV KHATAM ---
            
            tokens = get_tokens_for_user(user)

            return Response({
                'tokens': tokens,
                'role': 'staff', # Hamesha 'staff'
                'user_id': user.id
            }, status=status.HTTP_200_OK)

        except ValueError as e:
            logger.warning(f"Google Auth Error: {e}")
            return Response({"error": "Invalid Google token."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Google Login Error: {e}")
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# =======================================
# === STAFF/RIDER PASSWORD RESET ===
# =======================================

class StaffPasswordResetRequestView(generics.GenericAPIView):
    """
    Step 1: Staff/Rider ke phone number par password reset OTP bhejta hai.
    """
    serializer_class = StaffPasswordResetRequestSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data['phone_number']

        otp = random.randint(100000, 999999)
        send_otp_sms_task.delay(phone_number, otp)
        cache.set(f"reset_otp_{phone_number}", otp, timeout=300)

        return Response(
            {"success": "Password reset OTP aapke phone number par bhej diya gaya hai."}, 
            status=status.HTTP_200_OK
        )

class StaffPasswordResetConfirmView(generics.GenericAPIView):
    """
    Step 2: OTP verify karta hai aur naya password set karta hai.
    """
    serializer_class = StaffPasswordResetConfirmSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        phone_number = serializer.validated_data['phone_number']
        otp = int(serializer.validated_data['otp'])
        new_password = serializer.validated_data['new_password']

        cached_otp = cache.get(f"reset_otp_{phone_number}")

        if cached_otp is None or otp != cached_otp:
            return Response({"error": "Invalid or Expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(phone_number=phone_number)
            user.set_password(new_password)
            user.save()
            cache.delete(f"reset_otp_{phone_number}")

            return Response({"success": "Aapka password successfully reset ho gaya hai. Ab aap login kar sakte hain."}, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({"error": "User nahi mila."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"Ek error hui: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# =======================================
# === CUSTOMER PROFILE & ADDRESS ===
# =======================================

class CustomerProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CustomerProfileSerializer

    def get_object(self):
        profile, created = CustomerProfile.objects.get_or_create(user=self.request.user)
        return profile

class AddressListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = AddressSerializer

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user).order_by('-is_default', '-id')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = AddressSerializer

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

# =======================================
# === GENERAL ACCOUNT MANAGEMENT ===
# =======================================
        
class UpdateFCMTokenView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FCMTokenSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        fcm_token = serializer.validated_data['fcm_token']
        
        user = request.user
        user.fcm_token = fcm_token
        user.save(update_fields=['fcm_token'])
        
        return Response({"success": "FCM token updated successfully."}, status=status.HTTP_200_OK)

class DeleteAccountView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        # --- Guarded Imports ---
        from delivery.models import Delivery
        from wms.models import PickTask
        
        user = request.user
        should_anonymize = True 
        
        try:
            with transaction.atomic():
                user_lock = User.objects.select_for_update().get(pk=user.pk)

                if hasattr(user_lock, 'rider_profile'):
                    if Delivery.objects.filter(rider=user_lock.rider_profile).exists():
                        should_anonymize = False
                        logger.info(f"Deactivating Rider {user_lock.username} (has work history).")

                if hasattr(user_lock, 'store_staff_profile') and should_anonymize:
                    if PickTask.objects.filter(assigned_to=user_lock).exists():
                        should_anonymize = False
                        logger.info(f"Deactivating Staff {user_lock.username} (has work history).")

                user_lock.is_active = False
                user_lock.fcm_token = None
                
                if should_anonymize:
                    logger.info(f"Anonymizing Customer {user_lock.username}.")
                    user_lock.addresses.all().delete()
                    
                    timestamp = int(timezone.now().timestamp())
                    unique_id = f"del_{timestamp}"
                    
                    user_lock.username = unique_id
                    user_lock.phone_number = f"+{unique_id}"
                    user_lock.email = f"{unique_id}@deleted.com"
                    user_lock.first_name = "Anonymous"
                    user_lock.last_name = "User"
                    user_lock.profile_picture = None
                    
                    user_lock.save()
                    
                else:
                    if hasattr(user_lock, 'rider_profile'):
                        user_lock.rider_profile.is_online = False
                        user_lock.rider_profile.save(update_fields=['is_online'])
                        
                    user_lock.save(update_fields=['is_active', 'fcm_token'])

            return Response(
                {"success": "Aapka account successfully deactivate/anonymize kar diya gaya hai."}, 
                status=status.HTTP_204_NO_CONTENT
            )

        except Exception as e:
            logger.error(f"Account deletion failed for user {user.id}: {e}")
            return Response(
                {"error": "Account deletion failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )