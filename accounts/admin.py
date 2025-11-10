from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, CustomerProfile, StoreStaffProfile, Address
from delivery.models import RiderProfile 



class CustomerProfileInline(admin.StackedInline):
    model = CustomerProfile
    can_delete = False
    verbose_name_plural = 'Customer Profile'

class StoreStaffProfileInline(admin.StackedInline):
    model = StoreStaffProfile
    can_delete = False
    verbose_name_plural = 'Store Staff Profile'
    
class RiderProfileInline(admin.StackedInline):
    model = RiderProfile
    can_delete = False
    verbose_name_plural = 'Rider Profile'



@admin.register(User)
class UserAdmin(BaseUserAdmin):
   
    list_display = ('username', 'phone_number', 'email', 'first_name', 'last_name', 'is_staff')
    
   
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('username', 'phone_number', 'first_name', 'last_name', 'email')
    
   
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'phone_number', 'profile_picture')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    

    inlines = [CustomerProfileInline, RiderProfileInline, StoreStaffProfileInline]

    # --- YEH NAYA CODE ADD KAREIN ---
    actions = ['activate_users', 'deactivate_users']

    @admin.action(description="Chune hue users ko 'Active' karein")
    def activate_users(self, request, queryset):
        updated_count = queryset.update(is_active=True)
        self.message_user(request, f"{updated_count} users ko successfully activate kar diya gaya hai.")

    @admin.action(description="Chune hue users ko 'Deactivate' (Block) karein")
    def deactivate_users(self, request, queryset):
        # Admin ko deactivate na karein
        queryset = queryset.exclude(is_superuser=True)
        updated_count = queryset.update(is_active=False)
        self.message_user(request, f"{updated_count} users ko successfully deactivate (block) kar diya gaya hai.")
    # --- END NAYA CODE ---



@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'address_type', 'full_address', 'city', 'pincode', 'is_default')
    list_filter = ('address_type', 'city', 'is_default')
    search_fields = ('user__username', 'pincode', 'full_address')

@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user',)
    search_fields = ('user__username', 'user__phone_number')

@admin.register(StoreStaffProfile)
class StoreStaffProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'store', 'is_manager')
    list_filter = ('store', 'is_manager')
    search_fields = ('user__username', 'user__phone_number', 'store__name')