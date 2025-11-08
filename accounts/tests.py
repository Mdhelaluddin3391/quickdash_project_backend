# In accounts/tests.py

from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from accounts.models import User, Address, CustomerProfile
from delivery.models import RiderProfile, StoreStaffProfile # StoreStaffProfile import karein
from django.core.cache import cache

# ... (Aapka AuthTests aur ProfileAndAddressTests class waisa hi rahega) ...


# ======================================================
# NAYA TEST CLASS: PASSWORD RESET FEATURE KE LIYE
# ======================================================

# Celery tasks ko turant run karne ke liye aur cache ko mock karne ke liye
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
)
class PasswordResetTests(APITestCase):

    def setUp(self):
        # Ek Customer
        self.customer_user = User.objects.create_user(
            username='customer', phone_number='+91111', password='p1'
        )
        # Ek Rider
        self.rider_user = User.objects.create_user(
            username='rider', phone_number='+91222', password='p2'
        )
        RiderProfile.objects.create(user=self.rider_user)
        
        # Ek Staff
        self.staff_user = User.objects.create_user(
            username='staff', phone_number='+91333', password='p3'
        )
        StoreStaffProfile.objects.create(user=self.staff_user)

        self.request_url = reverse('staff-password-reset-request')
        self.confirm_url = reverse('staff-password-reset-confirm')
        
        cache.clear()

    def test_reset_request_fail_not_staff(self):
        """Test karein ki customer password reset request nahi kar sakta."""
        data = {'phone_number': self.customer_user.phone_number}
        response = self.client.post(self.request_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Yeh account staff ya rider account nahi hai', str(response.data))

    def test_reset_request_fail_no_user(self):
        """Test karein ki galat phone number fail hota hai."""
        data = {'phone_number': '+9199999'}
        response = self.client.post(self.request_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Is phone number se koi staff/rider account register nahi hai', str(response.data))

    def test_reset_request_success_rider(self):
        """Test karein ki rider ke liye OTP request success hoti hai."""
        data = {'phone_number': self.rider_user.phone_number}
        response = self.client.post(self.request_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Check karein ki OTP cache mein save hua hai
        cached_otp = cache.get(f"reset_otp_{self.rider_user.phone_number}")
        self.assertIsNotNone(cached_otp)
        self.assertTrue(isinstance(cached_otp, int))

    def test_reset_confirm_fail_wrong_otp(self):
        """Test karein ki galat OTP se password reset fail hota hai."""
        # Pehle cache mein OTP set karein
        cache.set(f"reset_otp_{self.rider_user.phone_number}", 1234, timeout=300)
        
        data = {
            'phone_number': self.rider_user.phone_number,
            'otp': 9999, # Galat OTP
            'new_password': 'NewPassword123',
            'confirm_password': 'NewPassword123'
        }
        response = self.client.post(self.confirm_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Galat OTP dala hai', str(response.data))

    def test_reset_confirm_fail_password_mismatch(self):
        """Test karein ki password mismatch par fail hota hai."""
        cache.set(f"reset_otp_{self.rider_user.phone_number}", 1234, timeout=300)
        
        data = {
            'phone_number': self.rider_user.phone_number,
            'otp': 1234,
            'new_password': 'NewPassword123',
            'confirm_password': 'WrongPassword123' # Mismatch
        }
        response = self.client.post(self.confirm_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Dono password match nahi karte', str(response.data))

    def test_reset_confirm_success(self):
        """
        CRITICAL: Test karein ki poora password reset flow sahi chalta hai
        aur naye password se login hota hai.
        """
        # 1. Request OTP
        self.test_reset_request_success_rider()
        
        # 2. Cache se OTP nikaalein (kyunki humein real OTP nahi pata)
        cached_otp = cache.get(f"reset_otp_{self.rider_user.phone_number}")
        self.assertIsNotNone(cached_otp)
        
        # 3. Confirm Reset
        new_pass = 'StrongPassword!123'
        data = {
            'phone_number': self.rider_user.phone_number,
            'otp': cached_otp,
            'new_password': new_pass,
            'confirm_password': new_pass
        }
        response = self.client.post(self.confirm_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('password successfully reset', str(response.data))
        
        # 4. Check karein ki OTP cache se delete ho gaya
        self.assertIsNone(cache.get(f"reset_otp_{self.rider_user.phone_number}"))
        
        # 5. Naye password se login karne ki koshish karein
        # (StaffLoginView ka istemaal karein)
        login_url = reverse('staff-login')
        login_data = {
            'phone_number': self.rider_user.phone_number,
            'password': new_pass
        }
        response = self.client.post(login_url, login_data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('tokens', response.data)
        self.assertEqual(response.data['role'], 'rider')