# delivery/admin.py
from django.contrib import admin
from .models import RiderProfile, Delivery, RiderEarning, RiderPayout, RiderCashDeposit
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal
from django.db import transaction

# --- NAYE IMPORTS (STEP 4.3) ---
from .models import RiderApplication, RiderDocument
from django.utils.html import format_html
from django.utils.safestring import mark_safe
# --- END NAYE IMPORTS ---


@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    # ... (Is class mein koi badlaav nahi)
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
    readonly_fields = ('cash_on_hand', 'application') # 'application' ko read-only add karein

@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    # ... (Is class mein koi badlaav nahi)
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


@admin.register(RiderEarning)
class RiderEarningAdmin(admin.ModelAdmin):
    # ... (Is class mein koi badlaav nahi)
    list_display = (
        'rider', 
        'order_id_str', 
        'base_fee', 
        'tip', 
        'total_earning', 
        'status',
        'created_at'
    )
    list_filter = ('rider', 'status', 'created_at')
    search_fields = ('rider__user__phone_number', 'order_id_str')
    readonly_fields = ('delivery', 'rider', 'order_id_str', 'base_fee', 'tip', 'total_earning', 'created_at', 'updated_at')
    actions = ['generate_payout_for_selected_earnings']
    
    @admin.action(description="Chuni hui UNPAID earnings ka Payout banayein")
    def generate_payout_for_selected_earnings(self, request, queryset):
        # ... (Is method mein koi badlaav nahi)
        unpaid_earnings = queryset.filter(status=RiderEarning.EarningStatus.UNPAID)
        if not unpaid_earnings.exists():
            self.message_user(request, "Koi UNPAID earning select nahi ki gayi.", level='warning')
            return
        riders = unpaid_earnings.values_list('rider', flat=True).distinct()
        if len(riders) > 1:
            self.message_user(request, "Error: Ek baar mein sirf ek hi rider ka payout banayein.", level='error')
            return
        rider_profile = RiderProfile.objects.get(id=riders[0])
        total_payout_amount = unpaid_earnings.aggregate(total=Sum('total_earning'))['total'] or Decimal('0.00')
        if total_payout_amount <= 0:
            self.message_user(request, "Total payout amount zero hai.", level='warning')
            return
        try:
            payout = RiderPayout.objects.create(
                rider=rider_profile,
                amount_paid=total_payout_amount,
                payment_date=timezone.now(),
                payment_method=RiderPayout.PayoutPaymentMethod.BANK_TRANSFER,
                notes=f"Admin {request.user.username} dwara generate kiya gaya payout."
            )
            payout.earnings_covered.set(unpaid_earnings)
            updated_count = unpaid_earnings.update(status=RiderEarning.EarningStatus.PAID)
            self.message_user(request, f"₹{total_payout_amount} ka Payout ID {payout.id} successfully ban gaya hai. {updated_count} earnings 'PAID' mark ho gayi hain.", level='success')
        except Exception as e:
            self.message_user(request, f"Payout create karte waqt error: {e}", level='error')
            
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False 

@admin.register(RiderPayout)
class RiderPayoutAdmin(admin.ModelAdmin):
    # ... (Is class mein koi badlaav nahi)
    list_display = ('id', 'rider', 'amount_paid', 'payment_date', 'payment_method', 'earning_count')
    list_filter = ('rider', 'payment_date', 'payment_method')
    search_fields = ('rider__user__phone_number', 'rider__user__username', 'notes')
    autocomplete_fields = ['rider']
    readonly_fields = ('amount_paid', 'created_at', 'updated_at', 'earning_count')
    fieldsets = (
        (None, {
            'fields': ('rider', 'amount_paid', 'payment_date', 'payment_method', 'notes')
        }),
        ('Covered Earnings', {
            'classes': ('collapse',),
            'fields': ('earnings_covered',),
        }),
    )
    filter_horizontal = ('earnings_covered',)
    def get_readonly_fields(self, request, obj=None):
        if obj: 
            return self.readonly_fields + ('rider', 'earnings_covered')
        return self.readonly_fields
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('earnings_covered')
    @admin.display(description='Earnings Count')
    def earning_count(self, obj):
        return obj.earnings_covered.count()
    def has_delete_permission(self, request, obj=None):
        return False 


@admin.register(RiderCashDeposit)
class RiderCashDepositAdmin(admin.ModelAdmin):
    # ... (Is class mein koi badlaav nahi)
    list_display = (
        'rider', 
        'amount', 
        'payment_method', 
        'transaction_id', 
        'status', 
        'created_at'
    )
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('rider__user__phone_number', 'transaction_id')
    autocomplete_fields = ['rider']
    fields = (
        'rider', 
        'amount', 
        'payment_method', 
        'transaction_id', 
        'notes', 
        'status',
        'admin_notes'
    )
    def get_readonly_fields(self, request, obj=None):
        if obj: 
            return [
                'rider', 
                'amount', 
                'payment_method', 
                'transaction_id', 
                'notes',
                'created_at'
            ]
        return ['status', 'admin_notes'] 
    actions = ['approve_selected_deposits', 'reject_selected_deposits']
    
    @admin.action(description="Chune hue PENDING deposits ko 'Approve' karein")
    def approve_selected_deposits(self, request, queryset):
        # ... (Is method mein koi badlaav nahi)
        pending_deposits = queryset.filter(status=RiderCashDeposit.DepositStatus.PENDING)
        if not pending_deposits.exists():
            self.message_user(request, "Koi pending deposit select nahi kiya gaya.", level='warning')
            return
        updated_count = 0
        failed_count = 0
        for deposit in pending_deposits:
            try:
                with transaction.atomic():
                    rider = RiderProfile.objects.select_for_update().get(id=deposit.rider.id)
                    rider.cash_on_hand = F('cash_on_hand') - deposit.amount
                    rider.save(update_fields=['cash_on_hand'])
                    deposit.status = RiderCashDeposit.DepositStatus.APPROVED
                    deposit.approved_by = request.user
                    if not deposit.admin_notes:
                        deposit.admin_notes = f"Approved by {request.user.username}."
                    deposit.save()
                updated_count += 1
            except Exception as e:
                failed_count += 1
                print(f"Failed to approve deposit {deposit.id}: {e}")
        if updated_count > 0:
            self.message_user(request, f"{updated_count} deposits successfully approve ho gaye hain.", level='success')
        if failed_count > 0:
             self.message_user(request, f"{failed_count} deposits approve nahi ho paaye. Error check karein.", level='error')

    @admin.action(description="Chune hue PENDING deposits ko 'Reject' karein")
    def reject_selected_deposits(self, request, queryset):
        # ... (Is method mein koi badlaav nahi)
        pending_deposits = queryset.filter(status=RiderCashDeposit.DepositStatus.PENDING)
        count = 0
        for deposit in pending_deposits:
            deposit.status = RiderCashDeposit.DepositStatus.REJECTED
            deposit.approved_by = request.user 
            if not deposit.admin_notes:
                 deposit.admin_notes = f"Rejected by {request.user.username}. Please contact admin."
            deposit.save()
            count += 1
        if count > 0:
            self.message_user(request, f"{count} deposits ko 'REJECTED' mark kar diya gaya hai.", level='info')


# --- NAYA ADMIN (STEP 4.3) ---

class RiderDocumentInline(admin.TabularInline):
    """
    Application ke andar documents ko (read-only) dikhane ke liye.
    """
    model = RiderDocument
    extra = 0 # Admin naya document add nahi kar sakta
    
    # Admin sirf 'is_verified' ko edit kar sakta hai
    readonly_fields = ('document_type', 'document_link')
    fields = ('document_type', 'document_link', 'is_verified')
    can_delete = False

    @admin.display(description="File Link")
    def document_link(self, obj):
        """
        Document file ke liye ek clickable link banata hai.
        """
        if obj.document_file:
            return mark_safe(f'<a href="{obj.document_file.url}" target="_blank">View Document</a>')
        return "No file uploaded"

    def has_add_permission(self, request, obj=None):
        return False # Admin yahaan se document add nahi karega

@admin.register(RiderApplication)
class RiderApplicationAdmin(admin.ModelAdmin):
    """
    Admin panel Rider Applications ko manage karne ke liye.
    """
    list_display = ('user', 'status', 'vehicle_details', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'user__phone_number', 'vehicle_details')
    
    # User ko create ke baad edit nahi kar sakte
    readonly_fields = ('user',)
    
    # Documents ko application ke andar hi dikhayein
    inlines = [RiderDocumentInline]
    
    fieldsets = (
        ('Application Info', {
            'fields': ('user', 'status', 'vehicle_details')
        }),
        ('Admin Review', {
            'fields': ('admin_notes',) # Admin yahaan notes likh sakta hai
        }),
    )

    # Naye Actions
    actions = ['approve_applications', 'reject_applications']

    @admin.action(description="Chuni hui PENDING applications ko 'Approve' karein")
    @transaction.atomic
    def approve_applications(self, request, queryset):
        """
        Selected applications ko approve karta hai aur unke liye RiderProfile banata hai.
        """
        # Sirf PENDING waalon par action lein
        pending_apps = queryset.filter(status=RiderApplication.ApplicationStatus.PENDING)
        approved_count = 0
        
        for app in pending_apps:
            user = app.user
            
            # Check karein ki profile pehle se toh nahi hai
            profile, created = RiderProfile.objects.get_or_create(user=user)
            
            if created:
                # Nayi profile bani hai
                profile.vehicle_details = app.vehicle_details
                profile.application = app # Profile ko application se link karein
                profile.save()
            else:
                # Profile pehle se thi (shayad admin ne banayi thi), use link karein
                profile.application = app
                profile.save(update_fields=['application'])

            # Application ko approve karein
            app.status = RiderApplication.ApplicationStatus.APPROVED
            if not app.admin_notes:
                app.admin_notes = f"Approved by {request.user.username} on {timezone.now().date()}"
            app.save(update_fields=['status', 'admin_notes'])
            
            approved_count += 1
            
        if approved_count > 0:
            self.message_user(request, f"{approved_count} applications successfully approve ho gayi hain. Rider profiles create/update ho gaye.", level='success')
        else:
            self.message_user(request, "Koi pending application select nahi ki gayi.", level='warning')

    @admin.action(description="Chuni hui PENDING applications ko 'Reject' karein")
    def reject_applications(self, request, queryset):
        """
        Selected applications ko reject karta hai.
        """
        # Sirf PENDING waalon par action lein
        pending_apps = queryset.filter(status=RiderApplication.ApplicationStatus.PENDING)
        
        updated_count = 0
        for app in pending_apps:
            app.status = RiderApplication.ApplicationStatus.REJECTED
            if not app.admin_notes:
                app.admin_notes = f"Rejected by {request.user.username} on {timezone.now().date()}"
            app.save(update_fields=['status', 'admin_notes'])
            updated_count += 1
            
        if updated_count > 0:
            self.message_user(request, f"{updated_count} applications 'Rejected' mark ho gayi hain.", level='info')
        else:
            self.message_user(request, "Koi pending application select nahi ki gayi.", level='warning')