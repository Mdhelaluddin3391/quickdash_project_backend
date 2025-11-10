import logging # <-- ADD
from celery import shared_task
# import time # <-- REMOVED (Unused)
from firebase_admin import messaging # <-- Consolidated to one import
from django.contrib.auth import get_user_model
import firebase_admin
# from firebase_admin import messaging # <-- REMOVED (Duplicate)
import requests
from django.conf import settings

User = get_user_model()
logger = logging.getLogger(__name__) # <-- ADD


# accounts/tasks.py

@shared_task
def send_otp_sms_task(phone_number, otp):
    """
    Ek background task jo OTP SMS bhejta hai (Updated with real API).
    """
    
    # Check karein ki settings mein keys hain ya nahi
    if not all([settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN, settings.TWILIO_PHONE_NUMBER]):
        logger.warning(f"Twilio settings missing for {phone_number}. Falling back to console.") # <-- CHANGED
        # FIX: Sensitive OTP ko log se hata diya
        logger.info(f"Mock SMS: OTP generated for {phone_number} (Dev only)") # <-- CHANGED
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

        logger.info(f"Sending real SMS to {phone_number} via Twilio...") # <-- CHANGED
        
        # API call karein
        response = requests.post(url, data=data, auth=auth, timeout=10) # 10 sec timeout

        # Check karein ki SMS gaya ya nahi
        if response.status_code == 201: # 201 = Created
            logger.info(f"Successfully sent SMS to {phone_number}. SID: {response.json().get('sid')}") # <-- CHANGED
            return f"SMS sent to {phone_number}"
        else:
            # Error hui toh log karein
            logger.error(f"Failed to send SMS to {phone_number}. Status: {response.status_code}, Response: {response.text}") # <-- CHANGED
            return f"Failed to send SMS: {response.text}"

    except requests.exceptions.RequestException as e:
        # Network error ya timeout
        logger.error(f"SMS API RequestException for {phone_number}: {e}") # <-- CHANGED
        return f"SMS API Request Failed: {e}"
    except Exception as e:
        # Koi aur error
        logger.error(f"General SMS task error for {phone_number}: {e}") # <-- CHANGED
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
        logger.error("FCM TASK ERROR: Firebase App not initialized. Skipping.") # <-- CHANGED
        return "Firebase App not initialized."

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning(f"FCM TASK ERROR: User with id {user_id} not found.") # <-- CHANGED
        return f"User {user_id} not found."
        
    if not user.fcm_token:
        logger.info(f"FCM TASK INFO: User {user.username} has no FCM token. Skipping.") # <-- CHANGED
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
        
        logger.info(f"Successfully sent push notification to {user.username}: {response}") # <-- CHANGED
        return f"Message sent to {user.username}"

    except Exception as e:
        logger.error(f"FCM TASK ERROR: Failed to send push to {user.username}: {e}") # <-- CHANGED
        # Agar token invalid hai, toh usse DB se nikaal dein
        if "registration-token-not-registered" in str(e) or \
           "invalid-registration-token" in str(e):
            logger.warning(f"Removing invalid FCM token for user {user.username}") # <-- CHANGED
            user.fcm_token = None
            user.save(update_fields=['fcm_token'])
            
        return f"Error sending to {user.username}: {e}"