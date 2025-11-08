from django.contrib import admin
from .models import StoreInventory

@admin.register(StoreInventory)
class StoreInventoryAdmin(admin.ModelAdmin):
    list_display = (
        'variant', 
        'store', 
        'price', 
        'sale_price', 
        'stock_quantity', 
        'is_available'
    )
    list_editable = (
        'price', 
        'sale_price', 
        'stock_quantity', 
        'is_available'
    )
    
    list_filter = ('store', 'is_available', 'variant__product__category')
    search_fields = (
        'variant__product__name', 
        'variant__variant_name', 
        'variant__sku', 
        'store__name'
    )
    
    autocomplete_fields = ['store', 'variant']