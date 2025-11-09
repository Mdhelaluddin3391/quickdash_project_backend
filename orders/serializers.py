# mdhelaluddin3B91/quickdash_project_backend/quickdash_project_backend-2eb660fd81f282e60785ee156912c7ed0e9f9ef6/orders/serializers.py

from rest_framework import serializers
from .models import Order, OrderItem
from accounts.serializers import AddressSerializer
from store.serializers import StoreSerializer
from delivery.serializers import DeliveryDetailSerializer 
from rest_framework import serializers
from .models import Order, OrderItem, Payment, Coupon 
from accounts.serializers import AddressSerializer
from store.serializers import StoreSerializer
from delivery.serializers import DeliveryDetailSerializer
from django.utils import timezone 
from decimal import Decimal 


class CouponSerializer(serializers.ModelSerializer):
    """Coupon ki basic info dikhane ke liye."""
    class Meta:
        model = Coupon
        fields = ['code', 'discount_type', 'discount_value']

class PaymentVerificationSerializer(serializers.Serializer):
    """
    Payment verification ke liye 
    """
    razorpay_order_id = serializers.CharField(required=True)
    razorpay_payment_id = serializers.CharField(required=True)
    razorpay_signature = serializers.CharField(required=True)
# --- END ---

class CheckoutSerializer(serializers.Serializer):
    """
    Checkout API (POST) ke liye INPUT serializer.
    """
    delivery_address_id = serializers.IntegerField(
        required=True,
        help_text="Customer ke saved addresses mein se ek ki ID"
    )
    payment_method = serializers.ChoiceField(
        choices=['COD', 'RAZORPAY'], 
        default='RAZORPAY'
    )
    special_instructions = serializers.CharField(
        required=False, 
        allow_blank=True,
        max_length=500
    )
    coupon_code = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50
    )
    rider_tip = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        default=Decimal('0.00'), 
        min_value=Decimal('0.00'), 
        help_text="Optional tip for the rider"
    )

    def validate_delivery_address_id(self, value):
        user = self.context['request'].user
        if not user.addresses.filter(id=value).exists():
            raise serializers.ValidationError("Invalid address ID.")
        return value

    def validate_coupon_code(self, code):
        """
        Validate karta hai ki coupon code valid hai ya nahi.
        """
        if not code: # Agar code empty hai
            return None
            
        try:
            # Case-insensitive match ke liye __iexact
            coupon = Coupon.objects.get(code__iexact=code)
        except Coupon.DoesNotExist:
            raise serializers.ValidationError("Invalid coupon code.")
        
        # Basic validity check (cart total ke bina)
        is_valid, message = coupon.is_valid(0) # 0 pass karein
        # Agar error 'Minimum purchase' ke alawa kuch hai, toh raise karein
        if not is_valid and "Minimum purchase" not in message:
             raise serializers.ValidationError(message)
             
        # Hum poora Coupon object return karenge, sirf code nahi
        return coupon


class OrderItemSerializer(serializers.ModelSerializer):
    """
    Order ke andar ke items ko dikhane ke liye.
    """
    item_total_price = serializers.FloatField(read_only=True)
    
    class Meta:
        model = OrderItem
        fields = [
            'id',
            'product_name',
            'variant_name',
            'price_at_order',
            'quantity',
            'item_total_price'
        ]

class OrderDetailSerializer(serializers.ModelSerializer):
    """
    Ek single order ki poori detail dikhane ke liye.
    """
    items = OrderItemSerializer(many=True, read_only=True)
    store = StoreSerializer(read_only=True)
    delivery_address = AddressSerializer(read_only=True)
    delivery = DeliveryDetailSerializer(read_only=True)
    coupon = CouponSerializer(read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'order_id',
            'status',
            'payment_status',
            'item_subtotal',
            'delivery_fee',
            'taxes_amount',
            'coupon',         
            'discount_amount',
            'rider_tip',
            'final_total',
            'special_instructions',
            'created_at',
            'store',
            'delivery_address',
            'items',
            'delivery'
        ]
        read_only_fields = fields

class OrderHistorySerializer(serializers.ModelSerializer):
    """
    Order history list ke liye halka (lightweight) serializer.
    """
    store_name = serializers.CharField(source='store.name', read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'order_id',
            'status',
            'final_total',
            'created_at',
            'store_name'
        ]
        read_only_fields = fields

# --- NAYA SERIALIZER ---
class RiderRatingSerializer(serializers.Serializer):
    """
    Rider ko rate karne ke liye INPUT serializer.
    """
    rating = serializers.IntegerField(
        required=True,
        min_value=1,
        max_value=5,
        help_text="Rating (1 se 5 star)"
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Optional comment for the rider"
    )
# --- END NAYA SERIALIZER ---