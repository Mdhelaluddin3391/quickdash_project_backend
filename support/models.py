import shortuuid
from django.db import models
from django.conf import settings
from orders.models import Order
from store.models import TimestampedModel # Hamara existing TimestampedModel

def generate_ticket_id():
    """Ek unique, human-readable Ticket ID generate karta hai"""
    return f"TKT-{shortuuid.ShortUUID().random(length=6).upper()}"

class SupportTicket(TimestampedModel):
    """
    Ek customer support request (e.g., "Order mein item galat tha").
    """
    class TicketStatus(models.TextChoices):
        OPEN = 'OPEN', 'Open' # Customer ne banaya/reply kiya
        PENDING = 'PENDING', 'Pending (Awaiting Customer Reply)' # Staff ne reply kiya
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress (Staff Working)' # Staff ne assign kiya
        RESOLVED = 'RESOLVED', 'Resolved' # Staff ne close kiya

    class TicketCategory(models.TextChoices):
        ORDER_ISSUE = 'ORDER_ISSUE', 'Order Issue'
        PAYMENT_ISSUE = 'PAYMENT_ISSUE', 'Payment Issue'
        DELIVERY_ISSUE = 'DELIVERY_ISSUE', 'Delivery Issue'
        TECHNICAL_ISSUE = 'TECHNICAL_ISSUE', 'Technical Issue'
        ACCOUNT_ISSUE = 'ACCOUNT_ISSUE', 'Account Issue'
        OTHER = 'OTHER', 'Other'

    # Ticket kisne banaya
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_tickets'
    )
    
    # Kis order ke baare mein hai (Optional)
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='support_tickets'
    )
    
    ticket_id = models.CharField(
        max_length=15, 
        default=generate_ticket_id, 
        unique=True, 
        db_index=True,
        editable=False
    )
    
    # Ticket ka subject/title
    subject = models.CharField(
        max_length=255,
        help_text="Aapki problem ka short title"
    )
    
    # Kis type ki problem hai
    category = models.CharField(
        max_length=20,
        choices=TicketCategory.choices,
        default=TicketCategory.OTHER
    )
    
    # Ticket ka current status
    status = models.CharField(
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.OPEN,
        db_index=True
    )
    
    # Kaun sa staff member isse handle kar raha hai (Admin se assign hoga)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_tickets',
        limit_choices_to={'is_staff': True} # Sirf staff ko assign kar sakte hain
    )
    
    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"[{self.ticket_id}] {self.subject} ({self.user.username})"


class TicketMessage(TimestampedModel):
    """
    Ek ticket ke andar ka har single message (chat ki tarah).
    """
    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    
    # Message kisne likha (customer ya staff)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )
    
    message = models.TextField()
    
    is_internal_note = models.BooleanField(
        default=False,
        help_text="Internal note (customer ko nahi dikhega)"
    )

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Message by {self.user.username} on {self.ticket.ticket_id}"

    def save(self, *args, **kwargs):
        """
        Jab naya message add ho, toh parent ticket ka status update karein.
        """
        is_new = self.pk is None # Check karein ki yeh naya message hai ya nahi
        super().save(*args, **kwargs)
        
        if is_new:
            # Ticket ko update karein
            ticket = self.ticket
            
            # Agar customer ne reply kiya hai (aur woh staff nahi hai)
            if not self.user.is_staff:
                ticket.status = SupportTicket.TicketStatus.OPEN
            # Agar staff ne reply kiya hai (aur yeh internal note nahi hai)
            elif self.user.is_staff and not self.is_internal_note:
                ticket.status = SupportTicket.TicketStatus.PENDING
            
            # updated_at timestamp ko manually update karein
            ticket.save(update_fields=['status', 'updated_at'])