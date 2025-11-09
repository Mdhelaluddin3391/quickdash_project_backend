# inventory/admin.py
from django.contrib import admin
from .models import StoreInventory
from wms.admin import WmsStockInline # <-- NAYA IMPORT

@admin.register(StoreInventory)
class StoreInventoryAdmin(admin.ModelAdmin):
    list_display = (
        'variant', 
        'store', 
        'price', 
        'sale_price', 
        'stock_quantity', # Yeh ab WmsStock se sync hoga
        'is_available'
    )
    list_editable = (
        'price', 
        'sale_price', 
        # 'stock_quantity', # <-- Ise yahaan se hata dein
        'is_available'
    )

    # stock_quantity ko readonly banayein kyunki yeh calculated hai
    readonly_fields = ('stock_quantity',)

    list_filter = ('store', 'is_available', 'variant__product__category')
    search_fields = (
        'variant__product__name', 
        'variant__variant_name', 
        'variant__sku', 
        'store__name'
    )

    autocomplete_fields = ['store', 'variant']

    # Naya Inline yahaan add karein
    inlines = [WmsStockInline]