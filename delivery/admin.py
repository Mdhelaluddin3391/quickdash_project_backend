from django.contrib import admin
from .models import RiderProfile, Delivery

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