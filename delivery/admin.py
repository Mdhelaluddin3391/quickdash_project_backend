from django.contrib import admin
from .models import RiderProfile, Delivery
# delivery/admin.py
from django.contrib import admin
from .models import RiderProfile, Delivery, RiderEarning # <-- NAYA IMPORT



@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user', 
        'is_online', 
        'on_delivery', 
        'vehicle_details', 
        'rating'
    )
    list_filter = ('is_online', 'on_delivery')
    search_fields = ('user__phone_number', 'user__username', 'vehicle_details')
    autocomplete_fields = ['user']

@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        'order', 
        'rider', 
        'status', 
        'accepted_at', 
        'picked_up_at', 
        'delivered_at'
    )
    list_filter = ('status', 'rider')
    search_fields = ('order__order_id', 'rider__user__phone_number')
    autocomplete_fields = ['order', 'rider']
    
    readonly_fields = ('accepted_at', 'at_store_at', 'picked_up_at', 'delivered_at')



# ... (RiderProfileAdmin aur DeliveryAdmin waise hi rahenge) ...

# --- NAYA ADMIN ---
@admin.register(RiderEarning)
class RiderEarningAdmin(admin.ModelAdmin):
    list_display = (
        'rider', 
        'order_id_str', 
        'base_fee', 
        'tip', 
        'total_earning', 
        'created_at'
    )
    list_filter = ('rider',)
    search_fields = ('rider__user__phone_number', 'order_id_str')
    readonly_fields = ('delivery', 'rider', 'order_id_str', 'base_fee', 'tip', 'total_earning', 'created_at', 'updated_at')
    
    def has_add_permission(self, request):
        return False # Isse manually create nahi karna hai
        
    def has_change_permission(self, request, obj=None):
        return False # Isse change nahi karna hai (sirf view)
# --- END NAYA ADMIN ---