from django.db import models
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from store.models import TimestampedModel
from orders.models import Order 
from accounts.tasks import send_fcm_push_notification_task

class RiderProfile(TimestampedModel):
    """
    Rider-specific details. 
    Yeh model 'accounts' app ke User (with role='RIDER') se juda hai.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='rider_profile',
    )
    
    current_location = gis_models.PointField(
        srid=4326, 
        null=True, 
        blank=True,
        help_text="Rider ki current live location (Longitude, Latitude)"
    )
    
    is_online = models.BooleanField(
        default=False, 
        db_index=True,
        help_text="Kya rider duty par hai aur orders ke liye available hai?"
    )
    on_delivery = models.BooleanField(
        default=False, 
        db_index=True,
        help_text="Kya rider abhi koi order deliver kar raha hai?"
    )
    
    vehicle_details = models.CharField(
        max_length=100, 
        blank=True,
        help_text="e.g., Bike - KA 01 AB 1234"
    )
    
    rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        null=True, 
        blank=True, 
        default=5.0
    )

    def __str__(self):
        status = "Online" if self.is_online else "Offline"
        return f"Rider: {self.user.username} ({status})"

    class Meta:
        verbose_name = "Rider Profile"
        verbose_name_plural = "Rider Profiles"


class Delivery(TimestampedModel):
    """
    Yeh model ek 'Order' ko ek 'Rider' se link karta hai aur
    delivery process ko track karta hai.
    """
    class DeliveryStatus(models.TextChoices):
        AWAITING_PREPARATION = 'AWAITING_PREPARATION', 'Awaiting Preparation'
        
        PENDING_ACCEPTANCE = 'PENDING_ACCEPTANCE', 'Pending Acceptance'
        ACCEPTED = 'ACCEPTED', 'Accepted'              
        AT_STORE = 'AT_STORE', 'At Store'                
        PICKED_UP = 'PICKED_UP', 'Picked Up'             
        DELIVERED = 'DELIVERED', 'Delivered'            
        CANCELLED = 'CANCELLED', 'Cancelled'   

    order = models.OneToOneField(
        Order, 
        on_delete=models.CASCADE,
        related_name='delivery'
    )
    
    rider = models.ForeignKey(
        RiderProfile, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='deliveries'
    )
    
    status = models.CharField(
        max_length=30, 
        choices=DeliveryStatus.choices, 
        default=DeliveryStatus.AWAITING_PREPARATION,
        db_index=True
    )

    accepted_at = models.DateTimeField(null=True, blank=True)
    at_store_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    estimated_delivery_time = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="Customer ko dikhane wala ETA"
    )



    def __str__(self):
        rider_name = self.rider.user.username if self.rider else "Unassigned"
        return f"Delivery for Order {self.order.order_id} by {rider_name}"

    def save(self, *args, **kwargs):
        """
        Custom save logic.
        Jab delivery ka status update hota hai, toh main 'Order' 
        ka status bhi update karein aur PUSH NOTIFICATION bhejein.
        """
        
        # Purana status check karne ke liye (agar naya object nahi hai)
        old_status = None
        if self.pk:
            try:
                old_status = Delivery.objects.get(pk=self.pk).status
            except Delivery.DoesNotExist:
                pass # Naya object hai
        
        # Order status update logic
        if self.status == self.DeliveryStatus.PICKED_UP:
            self.order.status = Order.OrderStatus.OUT_FOR_DELIVERY
        elif self.status == self.DeliveryStatus.DELIVERED:
            self.order.status = Order.OrderStatus.DELIVERED
        
        # Rider status update logic
        if self.rider:
            if self.status in [self.DeliveryStatus.ACCEPTED, self.DeliveryStatus.AT_STORE, self.DeliveryStatus.PICKED_UP]:
                self.rider.on_delivery = True
            elif self.status in [self.DeliveryStatus.DELIVERED, self.DeliveryStatus.CANCELLED]:
                self.rider.on_delivery = False
            self.rider.save()
        
        # Order ko save karein (taaki naya status DB mein jaaye)
        self.order.save()
        
        # --- PUSH NOTIFICATION TRIGGER LOGIC ---
        # Sirf tabhi notification bhejein jab status badla ho
        if old_status != self.status and self.order.user:
            user_id = self.order.user.id
            order_id = self.order.order_id
            
            title = f"Order {order_id} Update"
            body = None
            data = {"order_id": order_id, "status": self.status}
            
            if self.status == self.DeliveryStatus.ACCEPTED:
                rider_name = self.rider.user.first_name if self.rider and self.rider.user.first_name else "our delivery partner"
                body = f"{rider_name} aapka order lene jaa rahe hain."

            elif self.status == self.DeliveryStatus.PICKED_UP:
                body = "Aapka order rider ne pick up kar liya hai aur jald hi aapke paas hoga!"
            
            elif self.status == self.DeliveryStatus.DELIVERED:
                body = f"Aapka order {order_id} successfully deliver ho gaya hai. Thank you!"

            # Agar body set hui hai (yaani hum notification bhejna chahte hain)
            if body:
                try:
                    # Celery task ko call karein
                    send_fcm_push_notification_task.delay(user_id, title, body, data)
                except Exception as e:
                    # Celery down hone par bhi server crash na ho
                    print(f"Error triggering push notification task: {e}")
        # --- END NOTIFICATION LOGIC ---

        super(Delivery, self).save(*args, **kwargs)

    class Meta:
        verbose_name = "Delivery"
        verbose_name_plural = "Deliveries"
        ordering = ['-created_at']