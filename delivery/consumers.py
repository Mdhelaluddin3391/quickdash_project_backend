# quickdash_project/delivery/consumers.py
import json
from channels.generic.websocket import WebsocketConsumer
from asgiref.sync import async_to_sync

# --- SECURITY UPDATE ---
# In models ko import karein taaki hum user ko check kar sakein
from orders.models import Order
from delivery.models import RiderProfile
# --- END SECURITY UPDATE ---


class RiderNotificationConsumer(WebsocketConsumer):
    
    def connect(self):
        """
        Jab rider ka app WebSocket se connect hota hai.
        """
        # --- SECURITY UPDATE ---
        # AuthenticationMiddleware (jo aapne asgi.py mein lagaya hai)
        # self.scope['user'] mein user object daal deta hai.
        self.user = self.scope['user']

        # Check karein ki user authenticated hai aur uske paas RiderProfile hai
        if not (self.user and self.user.is_authenticated and hasattr(self.user, 'rider_profile')):
            
            # Agar nahi, toh connection reject kar dein
            self.close() # Self.close() likha tha, use self.close() kar diya
            return
        
        self.rider_profile = self.user.rider_profile
        self.rider_group_name = f"rider_{self.rider_profile.id}"
        # --- END SECURITY UPDATE ---

        # Har online rider ko "online_riders" group mein shaamil karo (Fallback ke liye)
        async_to_sync(self.channel_layer.group_add)(
            "online_riders",
            self.channel_name
        )
        
        # --- STEP 4.1: Rider ko uske personal group mein add karo ---
        async_to_sync(self.channel_layer.group_add)(
            self.rider_group_name,
            self.channel_name
        )
        # --- End STEP 4.1 ---
        
        self.accept()
        # Log mein username print karein, channel_name nahi
        print(f"Rider connected: {self.user.username}. Added to 'online_riders' and '{self.rider_group_name}'.")


    def disconnect(self, close_code):
        """
        Jab rider disconnect hota hai.
        """
        # --- SECURITY UPDATE ---
        # Agar user valid tha (connect ho paaya tha), tabhi group se discard karein
        if hasattr(self, 'user') and self.user.is_authenticated and hasattr(self, 'rider_group_name'):
        # --- END SECURITY UPDATE ---
            async_to_sync(self.channel_layer.group_discard)(
                "online_riders",
                self.channel_name
            )
            
            # --- STEP 4.2: Rider ko uske personal group se remove karo ---
            async_to_sync(self.channel_layer.group_discard)(
                self.rider_group_name,
                self.channel_name
            )
            # --- End STEP 4.2 ---
            
            print(f"Rider disconnected: {self.user.username}. Removed from groups.")

    # --- Group se message receive karne wale handlers ---

    def new_delivery_notification(self, event):
        """
        Yeh function tab call hoga jab 'online_riders' ya 'rider_...' group ko
        'type': 'new.delivery.notification' ka message milta hai.
        """
        delivery_data = event['delivery']
        
        # Rider ke app (client) ko JSON message bhejo
        self.send(text_data=json.dumps({
            'type': 'NEW_DELIVERY',
            'payload': delivery_data
        }))
        print(f"Sent NEW_DELIVERY notification to {self.user.username}")


class CustomerTrackingConsumer(WebsocketConsumer):
    
    def connect(self):
        """
        Jab customer 'Track Order' screen kholta hai.
        """
        # --- SECURITY UPDATE ---
        self.user = self.scope['user']
        # --- END SECURITY UPDATE ---

        # URL se order_id nikalein (e.g., /ws/track/QD1234/)
        self.order_id = self.scope['url_route']['kwargs']['order_id']
        self.order_group_name = f"order_{self.order_id}"

        # --- SECURITY UPDATE ---
        # Check karein ki user authenticated hai
        if not (self.user and self.user.is_authenticated):
            self.close()
            return

        try:
            # Check karein ki jo order_id URL mein hai, 
            # woh isi user ka hai ya nahi.
            if not Order.objects.filter(order_id=self.order_id, user=self.user).exists():
                # Agar user kisi aur ka order track karne ki koshish kar raha hai
                self.close()
                return
        except Exception:
            # Koi aur error (e.g., invalid order_id format)
            self.close()
            return
        # --- END SECURITY UPDATE ---
        
        # Customer ko uske specific order ke group mein add karein
        async_to_sync(self.channel_layer.group_add)(
            self.order_group_name,
            self.channel_name
        )

        self.accept()
        print(f"Customer connected: {self.user.username}. Added to '{self.order_group_name}'.")

    def disconnect(self, close_code):
        # --- SECURITY UPDATE ---
        # Agar user valid tha, tabhi group se discard karein
        if hasattr(self, 'order_group_name'):
        # --- END SECURITY UPDATE ---
            async_to_sync(self.channel_layer.group_discard)(
                self.order_group_name,
                self.channel_name
            )
            print(f"Customer disconnected: {self.user.username}. Removed from '{self.order_group_name}'.")

    def rider_location_update(self, event):
        """
        Yeh function tab call hoga jab 'order_...' group ko
        'type': 'rider.location.update' ka message milta hai.
        """
        location_data = event['location']
        
        # Customer ke app (client) ko JSON message bhejo
        self.send(text_data=json.dumps({
            'type': 'RIDER_LOCATION',
            'payload': location_data
        }))
        print(f"Sent RIDER_LOCATION notification to {self.channel_name}")