from django.contrib import admin

# Register your models here.
# wms/admin.py
from django.contrib import admin
from .models import Location, WmsStock, PickTask

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    """
    Admin panel mein Warehouse Locations (e.g., RACK-A) ko manage karne ke liye.
    """
    list_display = ('code', 'store', 'is_active', 'created_at')
    list_filter = ('store', 'is_active')
    search_fields = ('code', 'store__name')
    # 'store' ko dropdown ke bajaye search box (autocomplete) se select karein
    autocomplete_fields = ['store'] 


class WmsStockInline(admin.TabularInline):
    """
    Yeh 'StoreInventory' admin page ke andar granular stock dikhayega.
    """
    model = WmsStock
    extra = 0 # Naya add karne ke liye + button nahi dikhega (default)
    fields = ('location', 'quantity')
    autocomplete_fields = ['location']
    # Ise readonly rakhein taaki galti se yahaan se change na ho
    readonly_fields = ('location', 'quantity')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False # Yahaan se add nahi kar sakte

    def has_change_permission(self, request, obj=None):
        return False # Yahaan se edit nahi kar sakte


@admin.register(WmsStock)
class WmsStockAdmin(admin.ModelAdmin):
    """
    Admin panel mein granular stock (WmsStock) ko manage karne ke liye.
    """
    list_display = (
        'id', 
        'inventory_summary', 
        'location', 
        'quantity',
        'updated_at'
    )
    list_filter = ('inventory_summary__store', 'location')
    search_fields = (
        'inventory_summary__variant__sku',
        'inventory_summary__variant__product__name',
        'location__code'
    )
    autocomplete_fields = ['inventory_summary', 'location']

    # Quantity ko list se hi edit kar sakte hain
    list_editable = ('quantity',)


@admin.register(PickTask)
class PickTaskAdmin(admin.ModelAdmin):
    """
    Admin panel mein "Pick Tasks" ko monitor karne ke liye.
    """
    list_display = (
        'id',
        'order_id_str',
        'assigned_to',
        'status',
        'variant_sku',
        'quantity_to_pick',
        'location_code',
        'created_at'
    )
    list_filter = ('status', 'assigned_to', 'location__store')
    search_fields = (
        'order__order_id',
        'variant__sku',
        'assigned_to__phone_number',
        'location__code'
    )
    autocomplete_fields = ['order', 'location', 'variant', 'assigned_to']

    # Pick tasks ko admin se edit nahi karna chahiye (sirf view)
    readonly_fields = (
        'order', 
        'location', 
        'variant', 
        'quantity_to_pick', 
        'assigned_to', 
        'completed_at'
    )

    @admin.display(description='Order ID')
    def order_id_str(self, obj):
        return obj.order.order_id

    @admin.display(description='SKU')
    def variant_sku(self, obj):
        return obj.variant.sku

    @admin.display(description='Location')
    def location_code(self, obj):
        return obj.location.code

    def has_change_permission(self, request, obj=None):
        # Task ko change nahi karne denge, sirf 'status' change kar sakte hain
        # (woh bhi agar zaroorat ho, abhi ke liye False)
        return False

    def has_add_permission(self, request):
        return False # Task hamesha system se banne chahiye