# quickdash_project_backend/accounts/views.py

import random
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.cache import cache

# Model Imports
from .models import User, Address, CustomerProfile

# Serializer Imports
from .serializers import (
    OTPSerializer, 
    OTPVerifySerializer, 
    AddressSerializer, 
    CustomerProfileSerializer,
    StaffLoginSerializer,
    FCMTokenSerializer,
    StaffPasswordResetRequestSerializer,
    StaffPasswordResetConfirmSerializer
)

# Permission Imports
from .permissions import IsCustomer 

# Task Imports
from .tasks import send_otp_sms_task


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
        
    }

class SendOTPView(generics.GenericAPIView):
    serializer_class = OTPSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data['phone_number']

 
        otp = random.randint(1000, 9999)

        send_otp_sms_task.delay(phone_number, otp)

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

        session_otp = cache.get(f"otp_{phone_number}")

        if session_otp is None:
            return Response({"error": "First send OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if otp != session_otp:
            return Response({"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

        user, created = User.objects.get_or_create(
            phone_number=phone_number,
            defaults={'username': phone_number} 
        )

        if created:
            print(f"New user created: {user.username}")
        else:
            print(f"User logged in: {user.username}")

        tokens = get_tokens_for_user(user)

      
        cache.delete(f"otp_{phone_number}")
  

        return Response(tokens, status=status.HTTP_200_OK)

class StaffLoginView(generics.GenericAPIView):
    """
    Rider aur Store Staff ke (Phone + Password) Login ke liye.
    """
    serializer_class = StaffLoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        user = serializer.validated_data['user']
        
        tokens = get_tokens_for_user(user)
        
        # Frontend ko batane ke liye ki yeh user kaun hai
        role = "customer" 
        if hasattr(user, 'rider_profile'):
            role = "rider"
        elif hasattr(user, 'store_staff_profile'):
            role = "staff"

        return Response({
            'tokens': tokens,
            'role': role,
            'user_id': user.id
        }, status=status.HTTP_200_OK)

class CustomerProfileView(generics.RetrieveUpdateAPIView):
    """
    API endpoint: GET, PATCH /api/accounts/profile/
    Customer ko apni profile details (naam, email) dekhne aur update
    karne deta hai.
    """
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = CustomerProfileSerializer

    def get_object(self):
       
        profile, created = CustomerProfile.objects.get_or_create(user=self.request.user)
        return profile

class AddressListCreateView(generics.ListCreateAPIView):
    """
    API endpoint: GET, POST /api/accounts/addresses/
    Customer ke sabhi saved addresses list karta hai (GET).
    Customer ke liye naya address banata hai (POST).
    """
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = AddressSerializer

    def get_queryset(self):
  
        return Address.objects.filter(user=self.request.user).order_by('-is_default', '-id')

    def perform_create(self, serializer):
     
        serializer.save(user=self.request.user)

class AddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    API endpoint: GET, PUT, PATCH, DELETE /api/accounts/addresses/<pk>/
    Ek single address ko manage (view, update, delete) karne ke liye.
    """
    permission_classes = [permissions.IsAuthenticated, IsCustomer]
    serializer_class = AddressSerializer

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)




class DeleteAccountView(generics.GenericAPIView):
    """
    User ko "soft-delete" karta hai (account deactivate karta hai).
    User ka data (orders, etc.) database mein rehta hai.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        user = request.user
        
        # User ko delete karne ke bajaaye deactivate karein
        user.is_active = False
        
        # Optional: User ka FCM token clear kar dein
        user.fcm_token = None 
        
        user.save(update_fields=['is_active', 'fcm_token'])
        
        # Note: Humein user ko logout bhi karna chahiye.
        # SimpleJWT token ko server se invalidate karna mushkil hai,
        # isliye frontend (app) ko response milte hi token delete kar dena chahiye.
        
        return Response(
            {"success": "Aapka account successfully deactivate kar diya gaya hai."}, 
            status=status.HTTP_204_NO_CONTENT
        )

        
class UpdateFCMTokenView(generics.GenericAPIView):
    """
    API: POST /api/accounts/update-fcm-token/
    Authenticated user ka FCM token save/update karta hai.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FCMTokenSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        fcm_token = serializer.validated_data['fcm_token']
        
        # User object par token save karein
        user = request.user
        user.fcm_token = fcm_token
        user.save(update_fields=['fcm_token'])
        
        return Response({"success": "FCM token updated successfully."}, status=status.HTTP_200_OK)


class StaffPasswordResetRequestView(generics.GenericAPIView):
    """
    API: POST /api/accounts/staff-password-reset/
    Step 1: Staff/Rider ke phone number par password reset OTP bhejta hai.
    """
    serializer_class = StaffPasswordResetRequestSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone_number = serializer.validated_data['phone_number']

        # 4 digit ka OTP generate karein
        otp = random.randint(1000, 9999)

        # Celery task se OTP SMS bhejwaayein
        send_otp_sms_task.delay(phone_number, otp)

        # OTP ko cache mein save karein (5 minute ke liye)
        # Hum ek alag key 'reset_otp_' ka istemaal karenge taaki login OTP se conflict na ho
        cache.set(f"reset_otp_{phone_number}", otp, timeout=300)

        return Response(
            {"success": "Password reset OTP aapke phone number par bhej diya gaya hai."}, 
            status=status.HTTP_200_OK
        )

class StaffPasswordResetConfirmView(generics.GenericAPIView):
    """
    API: POST /api/accounts/staff-password-reset/confirm/
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

        # Cache se OTP nikaalein
        cached_otp = cache.get(f"reset_otp_{phone_number}")

        if cached_otp is None:
            return Response({"error": "OTP expired ya invalid hai. Dobara try karein."}, status=status.HTTP_400_BAD_REQUEST)

        if otp != cached_otp:
            return Response({"error": "Galat OTP dala hai."}, status=status.HTTP_400_BAD_REQUEST)

        # OTP sahi hai, ab user ka password update karein
        try:
            user = User.objects.get(phone_number=phone_number)
            
            # set_password() method password ko hash karne ke liye zaroori hai
            user.set_password(new_password)
            user.save()
            
            # OTP ko cache se delete karein
            cache.delete(f"reset_otp_{phone_number}")

            return Response({"success": "Aapka password successfully reset ho gaya hai. Ab aap login kar sakte hain."}, status=status.HTTP_200_OK)

        except User.DoesNotExist:
            return Response({"error": "User nahi mila."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"Ek error hui: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)