from django.contrib import admin
from .models import SupportTicket, TicketMessage

class TicketMessageInline(admin.TabularInline):
    """
    Ticket ke andar messages ko inline dikhane ke liye.
    """
    model = TicketMessage
    fields = ('user', 'message', 'is_internal_note', 'created_at')
    readonly_fields = ('created_at',)
    extra = 1 # Naya message add karne ke liye 1 blank form
    
    def get_formset(self, request, obj=None, **kwargs):
        """
        Naya message add karte waqt 'user' ko 'request.user' set karega.
        """
        formset = super().get_formset(request, obj, **kwargs)
        formset.form.base_fields['user'].initial = request.user
        return formset

@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        'ticket_id', 
        'subject', 
        'user', 
        'order_id_str', 
        'status', 
        'category', 
        'assigned_to', 
        'updated_at'
    )
    list_filter = ('status', 'category', 'assigned_to')
    search_fields = ('ticket_id', 'subject', 'user__phone_number', 'order__order_id')
    
    # Yeh fields sirf padh sakte hain, edit nahi
    readonly_fields = ('ticket_id', 'user', 'order', 'created_at', 'updated_at')
    
    # Admin is ticket ko assign kar sakta hai ya status change kar sakta hai
    autocomplete_fields = ['user', 'order', 'assigned_to']
    
    fieldsets = (
        (None, {
            'fields': ('ticket_id', 'user', 'order')
        }),
        ('Ticket Details', {
            'fields': ('subject', 'category', 'status', 'assigned_to')
        }),
    )
    
    # Messages ko ticket ke andar hi dikhayein
    inlines = [TicketMessageInline]
    
    @admin.display(description='Order ID')
    def order_id_str(self, obj):
        return obj.order.order_id if obj.order else 'N/A'

@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ('ticket_id_str', 'user', 'message_snippet', 'is_internal_note', 'created_at')
    list_filter = ('is_internal_note',)
    search_fields = ('ticket__ticket_id', 'user__phone_number', 'message')
    autocomplete_fields = ['ticket', 'user']
    readonly_fields = ('created_at',)

    @admin.display(description='Ticket ID')
    def ticket_id_str(self, obj):
        return obj.ticket.ticket_id

    @admin.display(description='Message')
    def message_snippet(self, obj):
        return obj.message[:50] + "..." if len(obj.message) > 50 else obj.message