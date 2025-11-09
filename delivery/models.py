# delivery/models.py (Updated with RiderEarning logic)

from django.db import models
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from store.models import TimestampedModel
from orders.models import Order 
from accounts.tasks import send_fcm_push_notification_task
from decimal import Decimal # <-- Import pehle se hai, acchi baat hai
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone # <-- YEH IMPORT ADD KAREIN
from django.db.models import F


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

    application = models.OneToOneField(
        'RiderApplication',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='profile'
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

    cash_on_hand = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Rider ke paas kitna COD cash hai jo usse company ko dena hai"
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


    rider_rating = models.PositiveIntegerField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Customer ne rider ko kya rating di (1-5)"
    )
    rider_rating_comment = models.TextField(
        blank=True, 
        null=True,
        help_text="Customer ka comment"
    )
    # --- END NAYE FIELDS ---



    def __str__(self):
        rider_name = self.rider.user.username if self.rider else "Unassigned"
        return f"Delivery for Order {self.order.order_id} by {rider_name}"

    def save(self, *args, **kwargs):
        """
        --- UPDATED SAVE METHOD ---
        Custom save logic.
        Ab yeh Order Status, Rider Status, Push Notification, aur Rider Earning
        sab manage karta hai.
        """
        
        # 1. Purana status check karein
        old_status = None
        if self.pk:
            try:
                old_status = Delivery.objects.get(pk=self.pk).status
            except Delivery.DoesNotExist:
                pass # Naya object hai
        
        # 2. Order status update logic
        if self.status == self.DeliveryStatus.PICKED_UP:
            self.order.status = Order.OrderStatus.OUT_FOR_DELIVERY
        elif self.status == self.DeliveryStatus.DELIVERED:
            self.order.status = Order.OrderStatus.DELIVERED
        
        # 3. Rider status update logic
        if self.rider:
            if self.status in [self.DeliveryStatus.ACCEPTED, self.DeliveryStatus.AT_STORE, self.DeliveryStatus.PICKED_UP]:
                self.rider.on_delivery = True
            elif self.status in [self.DeliveryStatus.DELIVERED, self.DeliveryStatus.CANCELLED]:
                self.rider.on_delivery = False
            self.rider.save()
        
        # 4. Order ko save karein (taaki naya status DB mein jaaye)
        self.order.save()
        
        # 5. Check karein ki status *sach mein* badla hai ya nahi
        status_changed = (old_status != self.status)
        
        # --- 6. PUSH NOTIFICATION TRIGGER LOGIC (Agar status badla hai) ---
        if status_changed and self.order.user:
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
        
        
        # --- 7. NAYA RIDER EARNING LOGIC (Agar status badla hai) ---
        # Jab order DELIVERED mark ho, tab earning record karein
        if status_changed and self.status == self.DeliveryStatus.DELIVERED and self.rider:
            try:
                # Base fee settings se lein
                base_fee = Decimal(getattr(settings, 'RIDER_BASE_DELIVERY_FEE', '0.00'))
                # Tip order se lein
                tip = self.order.rider_tip
                
                # Naya Earning record banayein
                RiderEarning.objects.create(
                    rider=self.rider,
                    delivery=self,
                    order_id_str=self.order.order_id,
                    base_fee=base_fee,
                    tip=tip,
                    total_earning=base_fee + tip
                )
                print(f"RiderEarning record created for Rider {self.rider.id} for Order {self.order.order_id}")
                
            except Exception as e:
                # Agar yeh fail bhi hota hai, toh order delivery ko na rokein
                print(f"ERROR: Failed to create RiderEarning record: {e}")
        # --- END NAYA LOGIC ---

        # 8. Ab main Delivery object ko save karein (BUG FIX)
        super(Delivery, self).save(*args, **kwargs)

    class Meta:
        verbose_name = "Delivery"
        verbose_name_plural = "Deliveries"
        ordering = ['-created_at']


# --- NAYA MODEL: RiderEarning ---
class RiderEarning(TimestampedModel):
    """
    Har successful delivery ke liye rider ki kamai track karta hai.
    """
    class EarningStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PAID = 'PAID', 'Paid'


    rider = models.ForeignKey(
        RiderProfile,
        on_delete=models.SET_NULL, # Rider delete ho jaaye toh bhi record rahe
        null=True,
        related_name='earnings'
    )
    delivery = models.OneToOneField(
        Delivery,
        on_delete=models.SET_NULL, # Delivery delete ho jaaye toh bhi record rahe
        null=True,
        related_name='earning_record'
    )
    order_id_str = models.CharField(
        max_length=15, 
        db_index=True,
        help_text="Order ID ka snapshot (search ke liye)"
    )
    
    base_fee = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Is delivery ke liye fix kamai"
    )
    tip = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        help_text="Customer se mili tip"
    )
    total_earning = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Kul kamai (Base Fee + Tip)"
    )

    status = models.CharField(
        max_length=10,
        choices=EarningStatus.choices,
        default=EarningStatus.UNPAID,
        db_index=True,
        help_text="Kya is kamai ka payment ho chuka hai?"
    )

    class Meta:
        verbose_name = "Rider Earning"
        verbose_name_plural = "Rider Earnings"
        ordering = ['-created_at']

    def __str__(self):
        rider_id = self.rider.id if self.rider else "N/A"
        return f"Earning {self.total_earning} for Rider {rider_id} (Order {self.order_id_str})"
# --- END NAYA MODEL ---



class RiderPayout(TimestampedModel):
    """
    Rider ko kiye gaye payments ka record (e.g., weekly bank transfer).
    """
    class PayoutPaymentMethod(models.TextChoices):
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
        CASH_ADJUSTMENT = 'CASH_ADJUSTMENT', 'Cash Adjustment'
        OTHER = 'OTHER', 'Other'

    rider = models.ForeignKey(
        RiderProfile,
        on_delete=models.PROTECT, # Payout record delete nahi hona chahiye agar rider hai
        related_name='payouts'
    )
    
    amount_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Rider ko kitna amount pay kiya gaya"
    )
    
    payment_date = models.DateTimeField(
        default=timezone.now,
        help_text="Payment kab process hua"
    )
    
    payment_method = models.CharField(
        max_length=20,
        choices=PayoutPaymentMethod.choices,
        default=PayoutPaymentMethod.BANK_TRANSFER
    )
    
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Admin ke liye notes (e.g., Transaction ID)"
    )
    
    # Yeh M2M field 'RiderEarning' ko is Payout se jodega
    earnings_covered = models.ManyToManyField(
        RiderEarning,
        related_name='payout_records',
        help_text="Is payout mein kaun si earnings shaamil hain"
    )

    class Meta:
        verbose_name = "Rider Payout"
        verbose_name_plural = "Rider Payouts"
        ordering = ['-payment_date']

    def __str__(self):
        return f"Payout {self.amount_paid} to {self.rider.user.username} on {self.payment_date.date()}"
    



class RiderCashDeposit(TimestampedModel):
    """
    Rider dwara company ko kiye gaye cash deposit (e.g., UPI transfer)
    ko track karta hai.
    """
    class DepositStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        
    class DepositPaymentMethod(models.TextChoices):
        UPI = 'UPI', 'UPI'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
        CASH = 'CASH', 'Cash'
        OTHER = 'OTHER', 'Other'

    rider = models.ForeignKey(
        RiderProfile,
        on_delete=models.PROTECT, # Hum deposit record delete nahi karna chahte
        related_name='cash_deposits'
    )
    
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Rider ne kitna amount deposit kiya"
    )
    
    payment_method = models.CharField(
        max_length=20,
        choices=DepositPaymentMethod.choices,
        default=DepositPaymentMethod.UPI
    )
    
    transaction_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text="UPI/Bank Transaction ID (Rider provide karega)"
    )
    
    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Rider ke notes (optional)"
    )
    
    status = models.CharField(
        max_length=10,
        choices=DepositStatus.choices,
        default=DepositStatus.PENDING,
        db_index=True
    )

    # Admin ke liye fields
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_deposits',
        help_text="Kis admin/staff ne approve kiya"
    )
    admin_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Admin ke notes (e.g., 'Checked in bank')"
    )
    
    class Meta:
        verbose_name = "Rider Cash Deposit"
        verbose_name_plural = "Rider Cash Deposits"
        ordering = ['-created_at']

    def __str__(self):
        return f"Deposit of {self.amount} by {self.rider.user.username} ({self.status})"
    


class RiderApplication(TimestampedModel):
    """
    Ek rider ki application ko track karta hai.
    """
    class ApplicationStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'   # Applicant ne submit kiya
        APPROVED = 'APPROVED', 'Approved' # Admin ne approve kiya
        REJECTED = 'REJECTED', 'Rejected' # Admin ne reject kiya

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='rider_application',
        help_text="Kaun sa user apply kar raha hai"
    )
    
    status = models.CharField(
        max_length=20,
        choices=ApplicationStatus.choices,
        default=ApplicationStatus.PENDING,
        db_index=True
    )
    
    vehicle_details = models.CharField(
        max_length=100,
        blank=True,
        help_text="Gaadi ka number (e.g., KA 01 AB 1234)"
    )

    admin_notes = models.TextField(
        blank=True,
        null=True,
        help_text="Admin ke notes (e.g., 'Rejected due to invalid license')"
    )

    class Meta:
        verbose_name = "Rider Application"
        verbose_name_plural = "Rider Applications"

    def __str__(self):
        return f"Application for {self.user.username} ({self.status})"

class RiderDocument(TimestampedModel):
    """
    Rider dwara upload kiye gaye documents (e.g., License, Aadhaar).
    """
    class DocumentType(models.TextChoices):
        DRIVING_LICENSE = 'DRIVING_LICENSE', 'Driving License'
        AADHAAR_CARD = 'AADHAAR_CARD', 'Aadhaar Card'
        VEHICLE_RC = 'VEHICLE_RC', 'Vehicle RC Book'
        OTHER = 'OTHER', 'Other'

    application = models.ForeignKey(
        RiderApplication,
        on_delete=models.CASCADE,
        related_name='documents',
        help_text="Yeh document kis application ka hissa hai"
    )
    
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices
    )
    
    # Hum 'FileField' ka istemaal karenge taaki PDF/Image dono aa sakein
    document_file = models.FileField(
        upload_to='rider_documents/',
        help_text="Document ki scan copy (Image/PDF)"
    )

    is_verified = models.BooleanField(
        default=False,
        help_text="Kya admin ne is document ko verify kar liya hai?"
    )

    class Meta:
        verbose_name = "Rider Document"
        verbose_name_plural = "Rider Documents"
        # Ek application mein ek type ka document ek hi baar
        unique_together = ('application', 'document_type')

    def __str__(self):
        return f"{self.get_document_type_display()} for {self.application.user.username}"