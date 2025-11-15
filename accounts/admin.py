# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
# GIS models ke liye 'admin.GISModelAdmin' ka istemaal karein
from django.contrib.gis import admin as gis_admin 
from .models import User, CustomerProfile, StoreStaffProfile, Address

# Inlines ko define karein taaki woh User admin mein dikh sakein
class CustomerProfileInline(admin.StackedInline):
    model = CustomerProfile
    can_delete = False
    verbose_name_plural = 'Customer Profile'

class StoreStaffProfileInline(admin.StackedInline):
    model = StoreStaffProfile
    can_delete = False
    verbose_name_plural = 'Store Staff Profile'

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Custom User Model ke liye Admin.
    """
    # User create karte waqt ke fields
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (None, {'fields': ('user_type', 'phone_number')}),
    )
    
    # User edit karte waqt ke fields
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Custom Info', {'fields': ('user_type', 'phone_number', 'profile_picture', 'fcm_token')}),
    )
    
    list_display = (
        'username', 
        'first_name', 
        'last_name', 
        'user_type', 
        'phone_number', 
        'is_staff'
    )
    list_filter = ('user_type', 'is_staff', 'is_superuser', 'is_active')
    search_fields = ('username', 'first_name', 'last_name', 'phone_number', 'email')
    
    # User ke andar hi uske profile ko display karein
    inlines = (CustomerProfileInline, StoreStaffProfileInline)

@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    """
    Customer Profile ke liye (halanki yeh User admin mein inline hai, 
    direct access bhi de rahe hain).
    """
    list_display = ('user', 'created_at')
    search_fields = ('user__username', 'user__phone_number')

@admin.register(StoreStaffProfile)
class StoreStaffProfileAdmin(admin.ModelAdmin):
    """
    Store Staff ko manage karne ke liye.
    """
    list_display = ('user', 'store', 'role', 'last_task_assigned_at')
    list_filter = ('store', 'role')
    search_fields = ('user__username', 'user__phone_number')
    autocomplete_fields = ('user', 'store') # Behtar UI ke liye

@admin.register(Address)
class AddressAdmin(gis_admin.GISModelAdmin):
    """
    User Addresses ke liye Admin (GIS enabled).
    Yeh 'location' field ke liye map dikhayega.
    """
    list_display = (
        'user', 
        'address_type', 
        'full_address', 
        'city', 
        'pincode', 
        'is_default'
    )
    list_filter = ('address_type', 'city', 'pincode', 'is_default')
    search_fields = ('user__username', 'full_address', 'pincode')
    autocomplete_fields = ('user',)