from rest_framework.permissions import BasePermission
from orders.models import Order, OrderItem

class HasPurchasedProduct(BasePermission):
    """
    Custom permission to only allow users who have purchased
    a specific product to review it.
    """
    message = "You must purchase this product to write a review."

    def has_permission(self, request, view):
        # Pehle check karein ki user authenticated hai
        if not (request.user and request.user.is_authenticated):
            return False
            
        # POST (create review) par hi check karna hai
        if request.method != 'POST':
            return True # GET (list reviews) sabke liye allowed hai

        product_id = view.kwargs.get('product_id')
        if not product_id:
            return False # Agar URL galat hai

        # Check karein ki user ke kisi bhi 'DELIVERED' order mein
        # yeh product_id hai ya nahi
        
        # Hum check kar rahe hain ki kya OrderItem exist karta hai:
        # 1. Jiska order 'DELIVERED' state mein hai
        # 2. Jiska order user ka hai
        # 3. Jiska product (variant ka product) wahi hai jise hum review kar rahe hain
        
        has_purchased = OrderItem.objects.filter(
            order__user=request.user,
            order__status=Order.OrderStatus.DELIVERED,
            inventory_item__variant__product__id=product_id
        ).exists()

        return has_purchased