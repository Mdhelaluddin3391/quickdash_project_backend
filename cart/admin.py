from django.contrib import admin
from .models import Cart, CartItem

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ('inventory_item', 'quantity', 'added_at')

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = (
        'user', 
        'store', 
        'item_count', 
        'total_price', 
        'updated_at'
    )
    search_fields = ('user__username', 'user__phone_number')
    inlines = [CartItemInline]