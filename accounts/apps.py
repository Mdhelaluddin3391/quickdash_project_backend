from django.apps import AppConfig
import logging
import firebase_admin
from firebase_admin import credentials
from django.conf import settings 

# Logger setup karein
logger = logging.getLogger(__name__)

class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        """
        AppConfig.ready() server start hote hi ek baar run hota hai.
        Yeh service initialization ke liye sahi jagah hai.
        """
        
        # --- FIX ---
        # Hum check karenge ki default app initialized hai ya nahi.
        # Iske liye internal variable (_DEFAULT_APP) ke bajaye
        # try...except block ka istemaal karna best practice hai.
        try:
            # Default app ko fetch karne ki koshish karein
            firebase_admin.get_app()
            # Agar upar waali line error nahi deti, iska matlab hai app pehle se initialized hai.
            # logger.info("Firebase App pehle se initialized hai.") # Yeh log zaroori nahi hai
        except ValueError:
            # Agar app initialized nahi hai, toh "ValueError: The default Firebase app does not exist" aata hai.
            # Ab hum ise initialize karenge
            key_file = settings.SERVICE_ACCOUNT_KEY_FILE
            
            if key_file.exists():
                try:
                    cred = credentials.Certificate(key_file)
                    firebase_admin.initialize_app(cred)
                    logger.info("Firebase Admin SDK Initialized Successfully.")
                except Exception as e:
                    logger.warning(f"Firebase Admin SDK failed to initialize: {e}")
            else:
                logger.warning("serviceAccountKey.json not found. Push notifications will not work.")
        
        # (Aapka create_user_profile signal @receiver se hai, isliye woh automatically load ho jayega)