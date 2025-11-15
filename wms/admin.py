# wms/admin.py
from django.contrib import admin
from .models import Location, WmsStock, PickTask

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    """
    Warehouse ke andar ki Locations (Racks/Shelves).
    """
    list_display = ('code', 'store', 'is_active')
    list_filter = ('store', 'is_active')
    search_fields = ('code', 'store__name')
    autocomplete_fields = ('store',)

@admin.register(WmsStock)
class WmsStockAdmin(admin.ModelAdmin):
    """
    Yeh REAL stock hai. Yahaan se aap stock ko add/edit/remove kar sakte hain.
    Yeh automatically 'StoreInventory' ko update kar dega.
    """
    list_display = (
        'inventory_summary', 
        'location', 
        'quantity'
    )
    list_filter = ('location__store', 'location')
    search_fields = (
        'inventory_summary__variant__product__name', 
        'inventory_summary__variant__sku', 
        'location__code'
    )
    # 'quantity' ko yahaan se edit kar sakte hain
    list_editable = ('quantity',)
    
    autocomplete_fields = ('inventory_summary', 'location')
    
    def get_queryset(self, request):
        # Behtar performance ke liye related models ko pre-fetch karein
        return super().get_queryset(request).select_related(
            'location', 
            'inventory_summary__variant__product',
            'inventory_summary__store'
        )

@admin.register(PickTask)
class PickTaskAdmin(admin.ModelAdmin):
    """
    Order picking tasks ko monitor karne ke liye.
    """
    list_display = (
        'order', 
        'variant', 
        'quantity_to_pick', 
        'location', 
        'status', 
        'assigned_to'
    )
    list_filter = ('status', 'assigned_to', 'location__store', 'created_at')
    search_fields = (
        'order__order_id', 
        'variant__sku', 
        'assigned_to__username', 
        'location__code'
    )
    
    # Admin se staff ko assign ya status change kar sakte hain
    list_editable = ('status', 'assigned_to')
    
    readonly_fields = (
        'order', 
        'location', 
        'variant', 
        'quantity_to_pick', 
        'picker_notes',
        'created_at',
        'updated_at',
        'completed_at'
    )
    autocomplete_fields = ('order', 'location', 'variant', 'assigned_to')