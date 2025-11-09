from django.db import models

# Create your models here.
# wms/models.py
from django.db import models
from django.conf import settings
from store.models import ProductVariant, Store, TimestampedModel # TimestampedModel ko import karein
from orders.models import Order
from inventory.models import StoreInventory # Yeh import zaroori hai

# --- Stock Synchronization ke liye Imports ---
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Sum

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
    # Design doc mein 'variant' tha, lekin 'inventory_summary' se
    # variant aur store dono mil jaate hain. Hum 'inventory_summary'
    # ko main link banayenge.
    inventory_summary = models.ForeignKey(
        StoreInventory, 
        on_delete=models.CASCADE,
        related_name='wms_entries',
        help_text="Yeh WMS entry kis StoreInventory item se judi hai"
    ) 
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='stock_items')
    quantity = models.PositiveIntegerField(default=0)

    # variant aur store ko denormalize kar sakte hain (optional, par faydemand)
    # variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    # store = models.ForeignKey(Store, on_delete=models.CASCADE)

    class Meta:
        # Ek location par ek inventory item ek hi baar aa sakta hai
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

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='pick_tasks')

    # Hum WmsStock se link kar sakte hain, ya location/variant se
    # Design doc ke hisaab se location/variant se karte hain:
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

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Pick {self.quantity_to_pick} x {self.variant.sku} from {self.location.code} for Order {self.order.order_id}"


# --- CRITICAL: Stock Synchronization Logic ---
# (Yeh wms_system_design_admin_mobile_picker.md se hai)

def update_inventory_summary(inventory_summary_id):
    """
    WmsStock ke aadhar par StoreInventory.stock_quantity ko update karta hai.
    """
    try:
        inv_summary = StoreInventory.objects.get(id=inventory_summary_id)

        total_qty = WmsStock.objects.filter(
            inventory_summary=inv_summary
        ).aggregate(
            total=Sum('quantity')
        )['total'] or 0

        # StoreInventory ko update karein
        inv_summary.stock_quantity = total_qty
        inv_summary.save(update_fields=['stock_quantity'])

        print(f"Updated StoreInventory {inv_summary.id}: New stock {total_qty}")

    except StoreInventory.DoesNotExist:
        print(f"Error: StoreInventory not found for id {inventory_summary_id}")
        pass

@receiver([post_save, post_delete], sender=WmsStock)
def on_wms_stock_change(sender, instance, **kwargs):
    """
    Jab bhi WmsStock (granular) badalta hai, 
    StoreInventory (summary) ko update karo.
    """
    print(f"WMS Stock changed for inventory_summary_id: {instance.inventory_summary_id}, updating summary...")
    update_inventory_summary(instance.inventory_summary_id)