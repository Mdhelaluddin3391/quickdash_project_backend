# inventory/admin.py
from django.contrib import admin
from .models import StoreInventory
from wms.models import WmsStock # WMS se import karein

class WmsStockInline(admin.TabularInline):
    """
    StoreInventory ke andar WMS ka granular stock dikhane ke liye.
    Yeh 'readonly' hai kyunki stock WMS app se manage hona chahiye.
    """
    model = WmsStock
    extra = 0
    fields = ('location', 'quantity')
    readonly_fields = ('location', 'quantity')
    can_delete = False
    verbose_name_plural = "WMS Granular Stock (Read-Only)"

    def has_add_permission(self, request, obj=None):
        return False # Yahaan se add nahi kar sakte

@admin.register(StoreInventory)
class StoreInventoryAdmin(admin.ModelAdmin):
    """
    Customer ko dikhne wala summary inventory.
    """
    list_display = (
        '__str__', # Model ka __str__ method use karega
        'store', 
        'price', 
        'sale_price', 
        'stock_quantity', # Yeh WMS se sync hota hai
        'is_available',
        'is_featured'
    )
    list_filter = ('store', 'is_available', 'is_featured', 'variant__product__category')
    search_fields = ('variant__product__name', 'variant__sku', 'store__name')
    list_editable = ('price', 'sale_price', 'is_available', 'is_featured')
    
    # stock_quantity ko readonly banayein kyunki yeh WMS se auto-update hota hai
    readonly_fields = ('stock_quantity', 'created_at', 'updated_at')
    
    autocomplete_fields = ('store', 'variant')
    
    inlines = [WmsStockInline] # WMS ka inline yahaan add karein