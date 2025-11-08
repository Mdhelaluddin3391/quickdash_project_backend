# accounts/tasks.py

from celery import shared_task
import time
from firebase_admin import messaging # <-- Naya import
from django.contrib.auth import get_user_model # <-- Naya import
import firebase_admin # <-- Naya import
from firebase_admin import messaging # <-- Naya import
import requests
from django.conf import settings

User = get_user_model()


# accounts/tasks.py

@shared_task
def send_otp_sms_task(phone_number, otp):
    """
    Ek background task jo OTP SMS bhejta hai (Updated with real API).
    """
    
    # --- Puraana Code ---
    # print(f"CELERY TASK: Sending SMS to {phone_number}...")
    # print(f"CELERY TASK: Sent OTP {otp} to {phone_number}")
    # return f"SMS sent to {phone_number}"
    # --- End Puraana Code ---

    # --- NAYA REAL API CALL (TWILIO EXAMPLE) ---
    
    # Check karein ki settings mein keys hain ya nahi
    if not all([settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_PHONE_NUMBER]):
        print(f"CELERY TASK (WARNING): Twilio settings missing. Falling back to console.")
        print(f"CELERY TASK (Mock SMS): OTP for {phone_number} is {otp}")
        return "Twilio settings missing. Mock SMS printed."

    try:
        # Twilio API URL
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Messages.json"
        
        # Data jo Twilio ko bhejna hai
        data = {
            "From": settings.TWILIO_PHONE_NUMBER,
            "To": phone_number, # e.g., +919876543210
            "Body": f"[QuickDash] Aapka OTP hai: {otp}. Yeh 5 minute ke liye valid hai."
        }
        
        # Basic Auth (Username = SID, Password = Auth Token)
        auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        print(f"CELERY TASK: Sending real SMS to {phone_number} via Twilio...")
        
        # API call karein
        response = requests.post(url, data=data, auth=auth, timeout=10) # 10 sec timeout

        # Check karein ki SMS gaya ya nahi
        if response.status_code == 201: # 201 = Created
            print(f"CELERY TASK: Successfully sent SMS to {phone_number}. SID: {response.json().get('sid')}")
            return f"SMS sent to {phone_number}"
        else:
            # Error hui toh log karein
            print(f"CELERY TASK ERROR: Failed to send SMS to {phone_number}.")
            print(f"Status Code: {response.status_code}, Response: {response.text}")
            return f"Failed to send SMS: {response.text}"

    except requests.exceptions.RequestException as e:
        # Network error ya timeout
        print(f"CELERY TASK ERROR (RequestException): {e}")
        return f"SMS API Request Failed: {e}"
    except Exception as e:
        # Koi aur error
        print(f"CELERY TASK ERROR (General): {e}")
        return f"SMS task failed: {e}"
    # --- END NAYA CODE ---

@shared_task
def send_fcm_push_notification_task(user_id, title, body, data=None):
    """
    --- UPDATED ---
    "REAL" Push Notification Task.
    Yeh Firebase (FCM) ko call karke user ko push notification bhejta hai.
    """
    
    # Check karein ki Firebase init hua hai ya nahi
    if not firebase_admin._DEFAULT_APP:
        print("FCM TASK ERROR: Firebase App not initialized. Skipping.")
        return "Firebase App not initialized."

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        print(f"FCM TASK ERROR: User with id {user_id} not found.")
        return f"User {user_id} not found."
        
    if not user.fcm_token:
        print(f"FCM TASK INFO: User {user.username} has no FCM token. Skipping.")
        return f"User {user.username} has no FCM token."

    try:
        # Step 1: Notification payload banayein
        notification = messaging.Notification(
            title=title,
            body=body
        )
        
        # Step 2: Message object banayein
        message = messaging.Message(
            notification=notification,
            data=data or {},
            token=user.fcm_token,
            
            # (Optional) Android app ke liye high priority set karein
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default'
                )
            ),
            # (Optional) iOS app ke liye sound set karein
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default'
                    )
                )
            )
        )

        # Step 3: Message Bhejein
        response = messaging.send(message)
        
        print(f"Successfully sent push notification to {user.username}: {response}")
        return f"Message sent to {user.username}"

    except Exception as e:
        print(f"FCM TASK ERROR: Failed to send push to {user.username}: {e}")
        # Agar token invalid hai, toh usse DB se nikaal dein
        if "registration-token-not-registered" in str(e) or \
           "invalid-registration-token" in str(e):
            print(f"Removing invalid FCM token for user {user.username}")
            user.fcm_token = None
            user.save(update_fields=['fcm_token'])
            
        return f"Error sending to {user.username}: {e}"