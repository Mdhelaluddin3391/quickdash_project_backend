# quickdash_project_backend/accounts/views.py

import random
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from delivery.models import Delivery
from wms.models import PickTask
# Model Imports
from .models import User, Address, CustomerProfile
# Serializer Imports
from django.conf import settings

from .serializers import (
    OTPSerializer, 
    OTPVerifySerializer, 
    AddressSerializer, 
    CustomerProfileSerializer,
    StaffLoginSerializer,
    FCMTokenSerializer,
    StaffPasswordResetRequestSerializer,
    StaffPasswordResetConfirmSerializer,
    StaffGoogleLoginSerializer
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

 
        # --- BUG FIX ---
        # 4-digit (1000, 9999) se 6-digit (100000, 999999) kiya gaya
        otp = random.randint(100000, 999999)
        # --- END BUG FIX ---

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
    --- UPDATED ---
    User ko "anonymize" (gumnaam) karta hai.
    - Customers: Saari personal details (address, phone, name) remove ho jaati hain.
    - Staff/Riders: Agar work history hai, toh account sirf deactivate hota hai
      taaki purane records (payouts, deliveries) kharaab na hon.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        user = request.user
        
        # Hum check karenge ki user ko "anonymize" karna hai ya sirf "deactivate"
        should_anonymize = True 
        
        try:
            with transaction.atomic():
                # User object ko lock karein
                user_lock = User.objects.select_for_update().get(pk=user.pk)

                # Check 1: Kya user Rider hai?
                if hasattr(user_lock, 'rider_profile'):
                    # Check karein ki kya rider ne kabhi koi delivery ki hai
                    if Delivery.objects.filter(rider=user_lock.rider_profile).exists():
                        should_anonymize = False
                        print(f"Rider {user_lock.username} ko deactivate kiya ja raha hai (work history hai).")

                # Check 2: Kya user Store Staff hai?
                if hasattr(user_lock, 'store_staff_profile') and should_anonymize:
                    # Check karein ki kya staff ne kabhi koi task pick kiya hai
                    if PickTask.objects.filter(assigned_to=user_lock).exists():
                        should_anonymize = False
                        print(f"Staff {user_lock.username} ko deactivate kiya ja raha hai (work history hai).")

                # Ab action lein
                
                user_lock.is_active = False
                user_lock.fcm_token = None
                
                if should_anonymize:
                    # Case A: Yeh ek Customer hai (ya staff/rider bina history ke)
                    # Inka saara data "gumnaam" kar do
                    
                    print(f"Customer {user_lock.username} ko anonymize kiya ja raha hai.")
                    
                    # 1. Saare addresses hamesha ke liye delete karein
                    user_lock.addresses.all().delete()
                    
                    # 2. Personal info ko badal dein
                    timestamp = int(timezone.now().timestamp())
                    unique_id = f"del_{timestamp}"
                    
                    user_lock.username = unique_id
                    user_lock.phone_number = f"+{unique_id}" # Phone number free kar dein
                    user_lock.email = f"{unique_id}@deleted.com" # Email free kar dein
                    user_lock.first_name = "Anonymous"
                    user_lock.last_name = "User"
                    user_lock.profile_picture = None # Profile pic hata dein
                    
                    # Save karein (saare fields update honge)
                    user_lock.save()
                    
                else:
                    # Case B: Yeh ek Staff/Rider hai jiska work data hai
                    # Inhe sirf deactivate karein, data nahi badlein
                    
                    # (Optional) Rider ko offline kar dein
                    if hasattr(user_lock, 'rider_profile'):
                        user_lock.rider_profile.is_online = False
                        user_lock.rider_profile.save(update_fields=['is_online'])
                        
                    # Sirf zaroori fields save karein
                    user_lock.save(update_fields=['is_active', 'fcm_token'])

            # Transaction successful
            return Response(
                {"success": "Aapka account successfully deactivate/anonymize kar diya gaya hai."}, 
                status=status.HTTP_204_NO_CONTENT
            )

        except Exception as e:
            # Agar transaction fail hua
            print(f"Account deletion failed for user {user.id}: {e}")
            return Response(
                {"error": "Account deletion failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
# --- END UPDATED VIEW ---
        
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

        # --- BUG FIX ---
        # 4-digit (1000, 9999) se 6-digit (100000, 999999) kiya gaya
        otp = random.randint(100000, 999999)
        # --- END BUG FIX ---

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
        

class StaffGoogleLoginView(generics.GenericAPIView):
    """
    API: POST /api/accounts/staff-google-login/
    Google 'id_token' ko verify karta hai aur staff ke liye login karta hai.
    """
    serializer_class = StaffGoogleLoginSerializer
    permission_classes = [permissions.AllowAny]

    # Aapko yeh settings.py mein add karna hoga
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
            # 1. Token ko Google se Verify karein
            id_info = id_token.verify_oauth2_token(
                token, 
                google_requests.Request(), 
                self.GOOGLE_CLIENT_ID
            )

            # 2. Email nikaalein
            email = id_info.get('email')
            if not email:
                raise Exception("Email not found in Google token.")

            # 3. Domain Check karein (Sabse zaroori step)
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

            # 4. User ko Database mein Check karein
            # Hum username ko email ka pehla hissa bana denge
            username = email.split('@')[0]
            
            user, created = User.objects.get_or_create(
                email__iexact=email, # Case-insensitive email check
                defaults={
                    'username': username,
                    'email': email,
                    'first_name': id_info.get('given_name', ''),
                    'last_name': id_info.get('family_name', ''),
                    'phone_number': None # Phone number zaroori nahi hai
                }
            )
            
            # 5. Check karein ki user Staff hai ya nahi
            if not hasattr(user, 'store_staff_profile') and not hasattr(user, 'rider_profile'):
                # Agar user naya bana hai ya staff nahi hai
                # Note: Aapko decide karna hai ki naye user ko automatically 
                # staff profile deni hai ya admin se banwani hai.
                # Abhi ke liye, hum maan rahe hain ki profile pehle se honi chahiye.
                return Response(
                    {"error": "Aapka company account register hai, lekin staff portal ke liye authorized nahi hai. Please admin se contact karein."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # 6. Role aur Tokens Generate karein
            tokens = get_tokens_for_user(user)
            role = "staff" # Default
            if hasattr(user, 'rider_profile'):
                role = "rider"
            elif hasattr(user, 'store_staff_profile'):
                role = "staff"

            return Response({
                'tokens': tokens,
                'role': role,
                'user_id': user.id
            }, status=status.HTTP_200_OK)

        except ValueError as e:
            # Invalid token
            print(f"Google Auth Error: {e}")
            return Response({"error": "Invalid Google token."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print(f"Google Login Error: {e}")
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)