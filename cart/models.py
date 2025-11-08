from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from inventory.models import StoreInventory
from store.models import Store 

class Cart(models.Model):
    """
    Har User (Customer) ke liye ek single cart.
    Yeh cart OneToOneField ke zariye User se juda hota hai.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE,
        related_name='cart',
        verbose_name="User"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Last Updated At"
    )

    def __str__(self):
        store_name = self.store.name if self.store else "Empty"
        return f"Cart for {self.user.username} (Store: {store_name})"

    @property
    def store(self) -> Store | None:
        """
        Cart kis store se associated hai.
        Yeh cart ke pehle item ke store se pata lagaya jaata hai.
        Agar cart khaali hai, toh None return hota hai.
        """
        first_item = self.items.first()
        if first_item:
            return first_item.inventory_item.store
        return None

    @property
    def total_price(self) -> float:
        """
        Cart mein sabhi items ki kul keemat calculate karta hai.
        """
        return sum(item.item_total_price for item in self.items.all())

    @property
    def item_count(self) -> int:
        """
        Cart mein total unique items (variants) ki ginti.
        """
        return self.items.count()
    
    @property
    def total_quantity(self) -> int:
        """
        Cart mein sabhi items ki kul quantity (e.g., 2 milk, 3 bread = 5).
        """
        return sum(item.quantity for item in self.items.all())

    class Meta:
        verbose_name = "Shopping Cart"
        verbose_name_plural = "Shopping Carts"


class CartItem(models.Model):
    """
    Shopping cart ke andar ka ek single item.
    Yeh 'Cart' aur 'StoreInventory' (jo ek specific store ka specific variant hai)
    ko jodta hai.
    """
    cart = models.ForeignKey(
        Cart, 
        on_delete=models.CASCADE, 
        related_name='items',
        verbose_name="Cart"
    )
    inventory_item = models.ForeignKey(
        StoreInventory, 
        on_delete=models.CASCADE,
        related_name='cart_items',
        help_text="Stock se ek specific item variant"
    )
    quantity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Is item ki kitni quantity"
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At"
    )

    class Meta:
        unique_together = ('cart', 'inventory_item')
        ordering = ['-added_at'] 
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"

    def __str__(self):
        try:
            return (
                f"{self.quantity} x "
                f"{self.inventory_item.variant.product.name} "
                f"({self.inventory_item.variant.variant_name})"
            )
        except Exception:
            return f"CartItem {self.id} (Quantity: {self.quantity})"

    @property
    def item_total_price(self) -> float:
        """
        Is cart item ki kul keemat (price * quantity).
        Yeh inventory se current price leta hai (sale price ya regular price).
        """
        return self.inventory_item.get_current_price * self.quantity