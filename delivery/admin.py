# delivery/admin.py
from django.contrib import admin
from .models import (
    RiderProfile, Delivery, RiderEarning, RiderPayout, 
    RiderCashDeposit, RiderApplication, RiderDocument
)
from accounts.models import User # User model import karein
from django.db import transaction

# --- Rider Application ke andar Inline ---

class RiderDocumentInline(admin.TabularInline):
    model = RiderDocument
    extra = 1
    fields = ('document_type', 'document_file', 'is_verified')
    
# --- Custom Actions ---

@admin.action(description='Approve selected applications')
def approve_applications(modeladmin, request, queryset):
    """
    Selected applications ko approve karne ke liye custom action.
    """
    for application in queryset.filter(status=RiderApplication.ApplicationStatus.PENDING):
        with transaction.atomic():
            # 1. Application status update karein
            application.status = RiderApplication.ApplicationStatus.APPROVED
            application.save()
            
            # 2. User ko 'RIDER' banayein
            user = application.user
            user.user_type = User.UserType.RIDER
            user.save()
            
            # 3. RiderProfile banayein
            profile, created = RiderProfile.objects.update_or_create(
                user=user,
                defaults={
                    'application': application,
                    'approval_status': RiderProfile.ApprovalStatus.APPROVED,
                    'vehicle_details': application.vehicle_details
                }
            )
    modeladmin.message_user(request, f"{queryset.count()} applications approved.")

@admin.action(description='Reject selected applications')
def reject_applications(modeladmin, request, queryset):
    queryset.update(status=RiderApplication.ApplicationStatus.REJECTED)
    modeladmin.message_user(request, f"{queryset.count()} applications rejected.")

@admin.register(RiderApplication)
class RiderApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'vehicle_details', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'vehicle_details')
    readonly_fields = ('user', 'created_at', 'updated_at')
    inlines = [RiderDocumentInline]
    actions = [approve_applications, reject_applications] # Actions add karein

@admin.register(RiderProfile)
class RiderProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user', 
        'approval_status', 
        'is_online', 
        'on_delivery', 
        'rating', 
        'cash_on_hand'
    )
    list_filter = ('approval_status', 'is_online', 'on_delivery')
    search_fields = ('user__username', 'user__phone_number', 'vehicle_details')
    list_editable = ('approval_status', 'is_online', 'on_delivery', 'cash_on_hand')
    autocomplete_fields = ('user', 'application')

@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ('order', 'rider', 'status', 'created_at')
    list_filter = ('status', 'rider')
    search_fields = ('order__order_id', 'rider__user__username')
    readonly_fields = (
        'order',
        'accepted_at', 
        'at_store_at', 
        'picked_up_at', 
        'delivered_at',
        'rider_rating',
        'rider_rating_comment'
    )
    autocomplete_fields = ('order', 'rider')

@admin.register(RiderEarning)
class RiderEarningAdmin(admin.ModelAdmin):
    list_display = ('rider', 'order_id_str', 'base_fee', 'tip', 'total_earning', 'status')
    list_filter = ('status', 'rider')
    search_fields = ('rider__user__username', 'order_id_str')
    readonly_fields = ('rider', 'delivery', 'order_id_str', 'base_fee', 'tip', 'total_earning')
    
    @admin.action(description='Mark selected earnings as PAID')
    def mark_as_paid(modeladmin, request, queryset):
        queryset.update(status=RiderEarning.EarningStatus.PAID)
    
    actions = [mark_as_paid]

@admin.register(RiderPayout)
class RiderPayoutAdmin(admin.ModelAdmin):
    list_display = ('rider', 'amount_paid', 'payment_date', 'payment_method')
    list_filter = ('payment_method', 'payment_date')
    search_fields = ('rider__user__username',)
    autocomplete_fields = ('rider',)
    # M2M field ke liye behtar UI
    filter_horizontal = ('earnings_covered',) 

@admin.register(RiderCashDeposit)
class RiderCashDepositAdmin(admin.ModelAdmin):
    list_display = ('rider', 'amount', 'payment_method', 'transaction_id', 'status')
    list_filter = ('status', 'payment_method')
    search_fields = ('rider__user__username', 'transaction_id')
    readonly_fields = ('rider', 'amount', 'payment_method', 'transaction_id', 'notes')
    
    @admin.action(description='Approve selected deposits')
    def approve_deposits(modeladmin, request, queryset):
        for deposit in queryset.filter(status=RiderCashDeposit.DepositStatus.PENDING):
            with transaction.atomic():
                deposit.status = RiderCashDeposit.DepositStatus.APPROVED
                deposit.approved_by = request.user
                deposit.save()
                # Rider ka cash_on_hand update karein
                deposit.rider.cash_on_hand -= deposit.amount
                deposit.rider.save(update_fields=['cash_on_hand'])

    @admin.action(description='Reject selected deposits')
    def reject_deposits(modeladmin, request, queryset):
        queryset.filter(status=RiderCashDeposit.DepositStatus.PENDING).update(
            status=RiderCashDeposit.DepositStatus.REJECTED,
            approved_by=request.user
        )

    actions = [approve_deposits, reject_deposits]