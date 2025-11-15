# cart/admin.py
from django.contrib import admin
from .models import Cart, CartItem

class CartItemInline(admin.TabularInline):
    """
    Cart ke andar ke items.
    """
    model = CartItem
    extra = 0
    fields = ('inventory_item', 'quantity', 'added_at', 'item_total_price')
    readonly_fields = ('added_at', 'item_total_price')
    autocomplete_fields = ('inventory_item',)

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """
    User shopping carts ko dekhne ke liye.
    """
    list_display = (
        'user', 
        'store', 
        'item_count', 
        'total_quantity', 
        'total_price', 
        'updated_at'
    )
    search_fields = ('user__username', 'user__phone_number')
    
    # Yeh sab calculated fields hain, isliye readonly
    readonly_fields = (
        'user',
        'store', 
        'item_count', 
        'total_quantity', 
        'total_price', 
        'created_at', 
        'updated_at'
    )
    
    inlines = [CartItemInline]