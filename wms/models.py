# wms/models.py
import logging # <-- ADD
from django.db import models
from django.conf import settings
from store.models import ProductVariant, Store, TimestampedModel # TimestampedModel ko import karein
from orders.models import Order
from inventory.models import StoreInventory # Yeh import zaroori hai

# --- Stock Synchronization ke liye Imports ---
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum

# Setup logger
logger = logging.getLogger(__name__) # <-- ADD


class Location(TimestampedModel): # TimestampedModel se inherit karein
    """
    Warehouse ke andar ki physical location (e.g., Rack A, Shelf 1)
    """
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='locations')
    code = models.CharField(
        max_length=50, 
        unique=True,
        help_text="Location ka unique code (e.g., 'A-01-R1-S1' ya 'RACK-A')"
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} at {self.store.name}"

class WmsStock(TimestampedModel): # TimestampedModel se inherit karein
    """
    Yeh batata hai ki KIS LOCATION par KIS ITEM ka kitna stock hai.
    Yeh granular stock level hai.
    """
    inventory_summary = models.ForeignKey(
        StoreInventory, 
        on_delete=models.CASCADE,
        related_name='wms_entries',
        help_text="Yeh WMS entry kis StoreInventory item se judi hai"
    ) 
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='stock_items')
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('inventory_summary', 'location')
        ordering = ['location__code']

    def __str__(self):
        return f"{self.quantity} x {self.inventory_summary.variant.sku} @ {self.location.code}"

class PickTask(TimestampedModel): # TimestampedModel se inherit karein
    """
    Picker ke mobile app ke liye ek single task.
    """
    class PickStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        ISSUE = 'ISSUE', 'Issue Reported' # <-- NAYA STATUS

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='pick_tasks')
    location = models.ForeignKey(
        Location, 
        on_delete=models.PROTECT,
        help_text="Kis location se uthana hai"
    )
    variant = models.ForeignKey(
        ProductVariant, 
        on_delete=models.PROTECT,
        help_text="Kaun sa item uthana hai"
    )
    quantity_to_pick = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20, 
        choices=PickStatus.choices, 
        default=PickStatus.PENDING,
        db_index=True
    )

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pick_tasks',
        help_text="Kaun sa picker yeh kaam karega (StoreStaff user)"
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    # --- NAYA FIELD ---
    picker_notes = models.TextField(
        blank=True, 
        null=True,
        help_text="Picker dwara report ki gayi issue (agar koi hai)"
    )
    # --- END NAYA FIELD ---

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Pick {self.quantity_to_pick} x {self.variant.sku} from {self.location.code} for Order {self.order.order_id}"


# --- CRITICAL: Stock Synchronization Logic ---
# (Yeh wms_system_design_admin_mobile_picker.md se hai)

def update_inventory_summary(inventory_summary_id):
    """
    WmsStock ke aadhar par StoreInventory.stock_quantity ko update karta hai.
    --- UPDATED: Ab yeh race conditions ko handle karne ke liye transaction ka istemaal karta hai ---
    """
    try:
        # --- START MODIFIED LOGIC ---
        
        # Ek naya database transaction shuru karein
        with transaction.atomic():
            # inv_summary row ko dhoondein aur usse LOCK karein
            # Jab tak yeh transaction poora nahi hota, koi aur process is row ko update nahi kar sakta
            inv_summary = StoreInventory.objects.select_for_update().get(id=inventory_summary_id)

            # Ab jab row locked hai, toh safely total calculate karein
            total_qty = WmsStock.objects.filter(
                inventory_summary=inv_summary
            ).aggregate(
                total=Sum('quantity')
            )['total'] or 0

            # Locked row ko naye total ke saath update karein
            inv_summary.stock_quantity = total_qty
            inv_summary.save(update_fields=['stock_quantity'])

            logger.info(f"WMS SYNC: Updated StoreInventory {inv_summary.id}: New stock {total_qty}")
        
        # --- END MODIFIED LOGIC ---

    except StoreInventory.DoesNotExist:
        logger.error(f"WMS SYNC ERROR: StoreInventory not found for id {inventory_summary_id}")
        pass
    except Exception as e:
        # Koi aur error (jaise database lock fail hona)
        logger.error(f"WMS SYNC FAILED for id {inventory_summary_id}: {e}")
        pass

@receiver([post_save, post_delete], sender=WmsStock)
def on_wms_stock_change(sender, instance, **kwargs):
    """
    Jab bhi WmsStock (granular) badalta hai, 
    StoreInventory (summary) ko update karo.
    """
    logger.info(f"WMS SYNC: WmsStock changed for inv_summary_id: {instance.inventory_summary_id}, updating summary...")
    update_inventory_summary(instance.inventory_summary_id)