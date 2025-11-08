from django.contrib import admin
from .models import Order, OrderItem, Payment
from .models import Order, OrderItem, Payment, Coupon

class OrderItemInline(admin.TabularInline):
    """
    Order page ke andar order ke items dikhata hai.
    """
    model = OrderItem
    extra = 0 
    readonly_fields = (
        'inventory_item', 
        'product_name', 
        'variant_name', 
        'price_at_order', 
        'quantity',
        'item_total_price'
    )
    can_delete = False

class PaymentInline(admin.TabularInline):
    """
    Order page ke andar payment details dikhata hai.
    """
    model = Payment
    extra = 0
    readonly_fields = (
        'transaction_id', 
        'payment_method', 
        'amount', 
        'status', 
        'created_at'
    )
    can_delete = False

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_id', 
        'user', 
        'store', 
        'status', 
        'payment_status', 
        'discount_amount',  # <-- Pehle se hona chahiye
        'rider_tip',
        'final_total', 
        'created_at'
    )
    list_filter = ('status', 'payment_status', 'store')
    search_fields = ('order_id', 'user__phone_number', 'user__username')
    
    readonly_fields = (
        'order_id', 'user', 'store', 'delivery_address', 
        'item_subtotal', 'delivery_fee', 'taxes_amount', 
        'coupon', 'discount_amount', 'rider_tip', # <-- Tip ko yahaan add karein
        'final_total', 'created_at', 'updated_at'
    )
    
    inlines = [OrderItemInline, PaymentInline]

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ('order', 'product_name', 'variant_name', 'price_at_order', 'quantity')
    search_fields = ('order__order_id', 'product_name')

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'order', 'amount', 'status', 'payment_method')
    list_filter = ('status', 'payment_method')
    search_fields = ('transaction_id', 'order__order_id')

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        'code', 
        'discount_type', 
        'discount_value', 
        'is_active', 
        'valid_to',
        'min_purchase_amount',
        'times_used',
        'max_uses'
    )
    list_filter = ('is_active', 'discount_type', 'valid_to')
    search_fields = ('code',)
    
    fieldsets = (
        (None, {
            'fields': ('code', 'is_active')
        }),
        ('Discount Details', {
            'fields': ('discount_type', 'discount_value', 'min_purchase_amount', 'max_discount_amount')
        }),
        ('Validity & Limits', {
            'fields': ('valid_from', 'valid_to', 'max_uses')
        }),
        ('Usage', {
            'fields': ('times_used',)
        }),
    )
    
    readonly_fields = ('times_used',)