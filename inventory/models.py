from django.db import models
from django.core.exceptions import ValidationError

from store.models import Store, ProductVariant, TimestampedModel

class StoreInventory(TimestampedModel):
    """
    Yeh model Q-Commerce ka core hai.
    Yeh batata hai ki KIS 'Store' mein, KAUN SA 'ProductVariant', 
    KIS 'Price' par, aur KITNI 'Quantity' mein available hai.
    """
    store = models.ForeignKey(
        Store, 
        on_delete=models.CASCADE,
        related_name='inventory_items',
        help_text="Kis dark store ka inventory item hai"
    )
    variant = models.ForeignKey(
        ProductVariant, 
        on_delete=models.CASCADE,
        related_name='inventory_entries',
        help_text="Kaun sa product variant (e.g., '500ml milk pouch')"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Customer ke liye Selling Price (MRP)"
    )
    sale_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Optional discounted price"
    )
    stock_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Is variant ka kitna stock available hai"
    )
    is_available = models.BooleanField(
        default=True,
        help_text="Kya yeh item abhi bikri ke liye available hai?"
    )

    class Meta:
        unique_together = ('store', 'variant')
        verbose_name_plural = "Store Inventories"

    def __str__(self):
        return f'{self.variant.product.name} ({self.variant.variant_name}) at {self.store.name}'

    def clean(self):
        if self.sale_price and self.sale_price > self.price:
            raise ValidationError("Sale price cannot be greater than the regular price.")
    
    @property
    def get_current_price(self):
        return self.sale_price if self.sale_price else self.price

    @property
    def is_on_sale(self):
        return self.sale_price is not None and self.sale_price < self.price

    @property
    def is_in_stock(self):
        return self.is_available and self.stock_quantity > 0