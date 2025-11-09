from django.contrib import admin
from .models import RiderProfile, Delivery,RiderPayout
# delivery/admin.py
from django.contrib import admin
from .models import RiderProfile, Delivery, RiderEarning # <-- NAYA IMPORT
from django.db.models import Sum # <-- NAYA IMPORT
from django.utils import timezone # <-- NAYA IMPORT
from decimal import Decimal # <-- NAYA IMPORT



@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user', 
        'is_online', 
        'on_delivery', 
        'vehicle_details', 
        'rating',
        'cash_on_hand'
    )
    list_filter = ('is_online', 'on_delivery')
    search_fields = ('user__phone_number', 'user__username', 'vehicle_details')
    autocomplete_fields = ['user']
    readonly_fields = ('cash_on_hand',)

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
        'status', # <-- NAYA FIELD
        'created_at'
    )
    list_filter = ('rider', 'status', 'created_at') # <-- NAYA FILTER
    search_fields = ('rider__user__phone_number', 'order_id_str')
    readonly_fields = ('delivery', 'rider', 'order_id_str', 'base_fee', 'tip', 'total_earning', 'created_at', 'updated_at')
    
    # --- NAYA ADMIN ACTION ---
    actions = ['generate_payout_for_selected_earnings']

    @admin.action(description="Chuni hui UNPAID earnings ka Payout banayein")
    def generate_payout_for_selected_earnings(self, request, queryset):
        
        # 1. Sirf 'UNPAID' earnings hi select karein
        unpaid_earnings = queryset.filter(status=RiderEarning.EarningStatus.UNPAID)
        
        if not unpaid_earnings.exists():
            self.message_user(request, "Koi UNPAID earning select nahi ki gayi.", level='warning')
            return

        # 2. Check karein ki sabhi earnings ek hi rider ki hain
        riders = unpaid_earnings.values_list('rider', flat=True).distinct()
        if len(riders) > 1:
            self.message_user(request, "Error: Ek baar mein sirf ek hi rider ka payout banayein.", level='error')
            return

        # 3. Payout amount calculate karein
        rider_profile = RiderProfile.objects.get(id=riders[0])
        total_payout_amount = unpaid_earnings.aggregate(total=Sum('total_earning'))['total'] or Decimal('0.00')

        if total_payout_amount <= 0:
            self.message_user(request, "Total payout amount zero hai.", level='warning')
            return

        try:
            # 4. Naya Payout object banayein
            payout = RiderPayout.objects.create(
                rider=rider_profile,
                amount_paid=total_payout_amount,
                payment_date=timezone.now(),
                payment_method=RiderPayout.PayoutPaymentMethod.BANK_TRANSFER,
                notes=f"Admin {request.user.username} dwara generate kiya gaya payout."
            )
            
            # 5. M2M field ko set karein
            payout.earnings_covered.set(unpaid_earnings)
            
            # 6. Sabhi earnings ko 'PAID' mark karein
            updated_count = unpaid_earnings.update(status=RiderEarning.EarningStatus.PAID)
            
            self.message_user(request, f"₹{total_payout_amount} ka Payout ID {payout.id} successfully ban gaya hai. {updated_count} earnings 'PAID' mark ho gayi hain.", level='success')

        except Exception as e:
            self.message_user(request, f"Payout create karte waqt error: {e}", level='error')
    # --- END NAYA ACTION ---

    def has_add_permission(self, request):
        return False
        
    def has_change_permission(self, request, obj=None):
        return False 
# --- END BADLAAV ---


# --- POORA NAYA ADMIN CLASS ---
@admin.register(RiderPayout)
class RiderPayoutAdmin(admin.ModelAdmin):
    list_display = ('id', 'rider', 'amount_paid', 'payment_date', 'payment_method', 'earning_count')
    list_filter = ('rider', 'payment_date', 'payment_method')
    search_fields = ('rider__user__phone_number', 'rider__user__username', 'notes')
    autocomplete_fields = ['rider']
    
    # Yeh fields sirf view-only hone chahiye jab payout ban jaaye
    readonly_fields = ('amount_paid', 'created_at', 'updated_at', 'earning_count')
    
    # 'earnings_covered' ko change view mein add karein
    fieldsets = (
        (None, {
            'fields': ('rider', 'amount_paid', 'payment_date', 'payment_method', 'notes')
        }),
        ('Covered Earnings', {
            'classes': ('collapse',),
            'fields': ('earnings_covered',),
        }),
    )
    
    # Yeh M2M field ko behtar UI dega
    filter_horizontal = ('earnings_covered',)
    
    def get_readonly_fields(self, request, obj=None):
        if obj: # Agar object pehle se bana hua hai (editing)
            # 'earnings_covered' ko bhi readonly kar dein taaki galti se change na ho
            return self.readonly_fields + ('rider', 'earnings_covered')
        return self.readonly_fields

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('earnings_covered')

    @admin.display(description='Earnings Count')
    def earning_count(self, obj):
        return obj.earnings_covered.count()
        
    def has_delete_permission(self, request, obj=None):
        return False # Payouts ko delete nahi karna chahiye