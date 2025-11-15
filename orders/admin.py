# orders/admin.py
from django.contrib import admin
from .models import Coupon, Order, OrderItem, Payment
from delivery.models import Delivery # Delivery se import karein

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    """
    Discount Coupons manage karne ke liye.
    """
    list_display = (
        'code', 
        'discount_type', 
        'discount_value', 
        'is_active', 
        'valid_from', 
        'valid_to', 
        'times_used', 
        'max_uses'
    )
    list_filter = ('discount_type', 'is_active', 'valid_to')
    search_fields = ('code',)
    list_editable = ('is_active', 'discount_value')

# --- Order ke andar Inlines ---

class OrderItemInline(admin.TabularInline):
    """
    Order ke andar ke items (snapshot).
    """
    model = OrderItem
    extra = 0
    fields = ('product_name', 'variant_name', 'price_at_order', 'quantity', 'item_total_price')
    readonly_fields = fields # Sab kuch readonly hai kyunki yeh snapshot hai

class PaymentInline(admin.TabularInline):
    """
    Order se jude payments.
    """
    model = Payment
    extra = 0
    fields = ('transaction_id', 'payment_method', 'amount', 'status', 'created_at')
    readonly_fields = fields

class DeliveryInline(admin.StackedInline):
    """
    Order se judi delivery details.
    """
    model = Delivery
    extra = 0
    fields = (
        'rider', 
        'status', 
        'accepted_at', 
        'picked_up_at', 
        'delivered_at',
        'rider_rating'
    )
    readonly_fields = ('accepted_at', 'picked_up_at', 'delivered_at', 'rider_rating')
    autocomplete_fields = ('rider',)
    
@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """
    Main Order Admin.
    """
    list_display = (
        'order_id', 
        'user', 
        'store', 
        'status', 
        'payment_status', 
        'final_total', 
        'created_at'
    )
    list_filter = ('status', 'payment_status', 'store', 'created_at')
    search_fields = ('order_id', 'user__username', 'user__phone_number', 'store__name')
    
    # Order banne ke baad yeh details change nahi honi chahiye
    readonly_fields = (
        'order_id', 'user', 'store', 'delivery_address',
        'item_subtotal', 'delivery_fee', 'taxes_amount', 
        'coupon', 'discount_amount', 'rider_tip', 'final_total',
        'special_instructions', 'created_at', 'updated_at'
    )
    
    # Details ko sections mein organize karein
    fieldsets = (
        ('Order Details', {
            'fields': ('order_id', 'status', 'payment_status', 'store', 'special_instructions')
        }),
        ('Customer Info', {
            'fields': ('user', 'delivery_address')
        }),
        ('Financials (Read-Only)', {
            'classes': ('collapse',), # Collapse kar ke rakhein
            'fields': (
                'item_subtotal', 
                'delivery_fee', 
                'taxes_amount', 
                'coupon', 
                'discount_amount', 
                'rider_tip', 
                'final_total'
            ),
        }),
    )
    
    inlines = [OrderItemInline, PaymentInline, DeliveryInline]

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """
    Sabhi Payments ko alag se manage karne ke liye.
    """
    list_display = ('transaction_id', 'order', 'payment_method', 'amount', 'status')
    list_filter = ('status', 'payment_method')
    search_fields = ('transaction_id', 'order__order_id', 'razorpay_order_id')