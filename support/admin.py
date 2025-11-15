# support/admin.py
from django.contrib import admin
from .models import SupportTicket, TicketMessage

class TicketMessageInline(admin.TabularInline):
    """
    Ticket ke andar ke messages.
    """
    model = TicketMessage
    extra = 1 # Staff yahaan se naya message add kar sakta hai
    fields = ('user', 'message', 'is_internal_note', 'created_at')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user',)
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Naya message by default current admin user ko assign karein
        if db_field.name == "user":
            kwargs["initial"] = request.user.id
            # Sirf staff users ko hi select karne dein
            kwargs["queryset"] = User.objects.filter(is_staff=True) 
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_id', 
        'subject', 
        'user', 
        'status', 
        'category', 
        'assigned_to', 
        'updated_at'
    )
    list_filter = ('status', 'category', 'assigned_to', 'created_at')
    search_fields = ('ticket_id', 'subject', 'user__username', 'order__order_id')
    
    # User aur order ko readonly rakhein
    readonly_fields = ('ticket_id', 'user', 'order', 'created_at', 'updated_at')
    
    # Status aur assigned_to ko edit kar sakte hain
    list_editable = ('status', 'assigned_to')
    
    autocomplete_fields = ('user', 'order', 'assigned_to')
    
    inlines = [TicketMessageInline]