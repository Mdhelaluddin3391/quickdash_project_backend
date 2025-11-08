import shortuuid
from django.db import models
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from accounts.models import Address
from store.models import Store, ProductVariant, TimestampedModel
from inventory.models import StoreInventory
from django.utils import timezone #
from django.core.validators import MinValueValidator, MaxValueValidator # <-- Naya import

def generate_order_id():
    """Ek unique, human-readable Order ID generate karta hai"""
    return shortuuid.ShortUUID().random(length=8).upper()
class Coupon(TimestampedModel):
    """
    Discount coupons ke liye model.
    """
    class DiscountType(models.TextChoices):
        PERCENTAGE = 'PERCENTAGE', 'Percentage'
        FIXED_AMOUNT = 'FIXED_AMOUNT', 'Fixed Amount'

    code = models.CharField(
        max_length=50, 
        unique=True, 
        db_index=True,
        help_text="Coupon code (e.g., 'SAVE10', 'FREEDELIVERY')"
    )
    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.FIXED_AMOUNT
    )
    # value = 10% (10.00) ya ₹100 (100.00)
    discount_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Discount value (e.g., 10.00 for 10% or 100.00 for ₹100)"
    )
    min_purchase_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        help_text="Coupon istemaal karne ke liye minimum cart total"
    )
    max_discount_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Percentage coupons ke liye maximum discount limit"
    )
    valid_from = models.DateTimeField(
        default=timezone.now
    )
    valid_to = models.DateTimeField(
        help_text="Coupon ki expiry date/time"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Kya yeh coupon abhi active hai?"
    )
    max_uses = models.PositiveIntegerField(
        default=100,
        help_text="Yeh coupon kitni baar istemaal ho sakta hai (total)"
    )
    times_used = models.PositiveIntegerField(
        default=0,
        editable=False,
        help_text="Yeh coupon kitni baar istemaal ho chuka hai"
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.code

    def is_valid(self, cart_total):
        """
        Check karta hai ki coupon valid hai ya nahi (cart total ke aadhar par).
        Return: (True, "Valid") ya (False, "Error Message")
        """
        if not self.is_active:
            return False, "Coupon is not active."
        if timezone.now() < self.valid_from:
            return False, "Coupon is not yet valid."
        if timezone.now() > self.valid_to:
            return False, "Coupon has expired."
        if self.times_used >= self.max_uses:
            return False, "Coupon has reached its usage limit."
        if cart_total < self.min_purchase_amount:
            return False, f"Minimum purchase of ₹{self.min_purchase_amount} required."
        
        return True, "Coupon is valid."

    def calculate_discount(self, cart_total):
        """
        Cart total ke aadhar par discount amount calculate karta hai.
        """
        if self.discount_type == self.DiscountType.PERCENTAGE:
            discount = (cart_total * self.discount_value) / 100
            if self.max_discount_amount and discount > self.max_discount_amount:
                return self.max_discount_amount
            return discount.quantize(Decimal('0.01'))
            
        elif self.discount_type == self.DiscountType.FIXED_AMOUNT:
            # Discount cart total se zyada nahi ho sakta
            return min(self.discount_value, cart_total)
        
        return Decimal('0.00')


class Order(TimestampedModel):
    """
    Checkout ke baad create hua main order object.
    Yeh cart ka ek permanent snapshot hota hai.
    """
    class OrderStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'              
        CONFIRMED = 'CONFIRMED', 'Confirmed'            
        PREPARING = 'PREPARING', 'Preparing'           
        READY_FOR_PICKUP = 'READY_FOR_PICKUP', 'Ready for Pickup' 
        OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY', 'Out for Delivery' 
        DELIVERED = 'DELIVERED', 'Delivered'         
        CANCELLED = 'CANCELLED', 'Cancelled'            
        FAILED = 'FAILED', 'Failed'                   

    class PaymentStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        SUCCESSFUL = 'SUCCESSFUL', 'Successful'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    order_id = models.CharField(
        max_length=15, 
        default=generate_order_id, 
        unique=True, 
        db_index=True,
        editable=False,
        verbose_name="Order ID"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='orders'
    )
    store = models.ForeignKey(
        Store, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='orders'
    )
    delivery_address = models.ForeignKey(
        Address, 
        on_delete=models.SET_NULL, 
        null=True,
        help_text="Order ke waqt select kiya gaya address"
    )

    status = models.CharField(
        max_length=20, 
        choices=OrderStatus.choices, 
        default=OrderStatus.PENDING,
        db_index=True
    )
    payment_status = models.CharField(
        max_length=20, 
        choices=PaymentStatus.choices, 
        default=PaymentStatus.PENDING,
        db_index=True
    )
    
    item_subtotal = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Sirf items ka total price"
    )
    delivery_fee = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00
    )
    taxes_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        verbose_name="Taxes"
    )

    # --- STEP 1.2: NAYE COUPON FIELDS ORDER MEIN ADD KAREIN ---
    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.SET_NULL, # Coupon delete hone par bhi order valid rahe
        null=True,
        blank=True,
        related_name='orders',
        help_text="Is order par apply kiya gaya coupon"
    )
    discount_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        verbose_name="Discount Amount"
    )
    rider_tip = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        verbose_name="Rider Tip",
        help_text="Customer dwara di gayi tip"
    )
    final_total = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        verbose_name="Grand Total",
        help_text="Subtotal + Delivery Fee + Taxes - Discount"
    )

    special_instructions = models.TextField(
        null=True, 
        blank=True,
        help_text="Customer ke special instructions (e.g., 'less spicy')"
    )

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ['-created_at']

    def __str__(self):
        return f"Order {self.order_id} by {self.user.username}"

class OrderItem(models.Model):
    """
    Order ke andar ka har ek item.
    Yeh data denormalized hai (price, name copy kiya jaata hai).
    """
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    inventory_item = models.ForeignKey(
        StoreInventory, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )

    
    product_name = models.CharField(
        max_length=255,
        help_text="Product ka naam (snapshot)"
    )
    variant_name = models.CharField(
        max_length=255,
        help_text="Variant ka naam (snapshot)"
    )
    price_at_order = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Item ka price (snapshot)"
    )
    quantity = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.quantity} x {self.product_name} ({self.variant_name}) @ {self.price_at_order}"

    @property
    def item_total_price(self) -> float:
        return self.price_at_order * self.quantity

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"


class Payment(TimestampedModel):
    """
    Har order se juda payment transaction.
    """
    class PaymentMethod(models.TextChoices):
        COD = 'COD', 'Cash on Delivery'
        STRIPE = 'STRIPE', 'Stripe'
        RAZORPAY = 'RAZORPAY', 'Razorpay'
        OTHER = 'OTHER', 'Other'

    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='payments'
    )
    razorpay_order_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        db_index=True,
        help_text="Razorpay se mili Order ID"
    )
    transaction_id = models.CharField(
        max_length=255, 
        unique=True, 
        db_index=True,
        help_text="Payment gateway se mili ID (e.g., razorpay_payment_id)"
    )
    payment_method = models.CharField(
        max_length=20, 
        choices=PaymentMethod.choices, 
        default=PaymentMethod.COD
    )
    amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Kitna amount pay hua"
    )
    status = models.CharField(
        max_length=20, 
        choices=Order.PaymentStatus.choices,
        default=Order.PaymentStatus.PENDING
    )
    payment_gateway_response = models.JSONField(
        default=dict, 
        blank=True,
        help_text="Gateway se mila poora response (JSON)"
    )

    def __str__(self):
        return f"Payment {self.transaction_id} for Order {self.order.order_id}"