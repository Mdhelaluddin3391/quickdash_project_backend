# accounts/tasks.py

from celery import shared_task
import time
from firebase_admin import messaging # <-- Naya import
from django.contrib.auth import get_user_model # <-- Naya import
import firebase_admin # <-- Naya import

User = get_user_model()


@shared_task
def send_otp_sms_task(phone_number, otp):
    """
    Ek background task jo OTP SMS bhejta hai.
    """
    print(f"CELERY TASK: Sending SMS to {phone_number}...")
    # Yahaan real SMS gateway API call hogi
    print(f"CELERY TASK: Sent OTP {otp} to {phone_number}")
    
    return f"SMS sent to {phone_number}"


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