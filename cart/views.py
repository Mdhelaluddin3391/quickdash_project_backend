# cart/views.py
import logging # <-- ADD
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import Cart, CartItem
from inventory.models import StoreInventory
from .serializers import (
    CartSerializer, 
    CartItemAddSerializer, 
    CartItemUpdateSerializer
)
from accounts.permissions import IsCustomer 

# Setup logger
logger = logging.getLogger(__name__) # <-- ADD


class CartDetailView(generics.RetrieveAPIView):
    """
    (UPDATED with prefetch for optimization)
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = CartSerializer

    def get_object(self):
        # --- BUG FIX: N+1 QUERY ---
        cart, created = Cart.objects.prefetch_related(
            'items__inventory_item__variant__product__category',
            'items__inventory_item__store',
            'store'
        ).get_or_create(user=self.request.user)
        return cart
        # --- END BUG FIX ---


class CartItemAddView(generics.GenericAPIView):
    """
    API endpoint: POST /api/cart/add/
    Cart mein naya item add karta hai, ya maujooda item ki quantity badhaata hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = CartItemAddSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        inventory_item_id = serializer.validated_data['inventory_item_id']
        quantity_to_add = serializer.validated_data['quantity']
        
    
        inventory_item = StoreInventory.objects.get(id=inventory_item_id)
        
        cart, _ = Cart.objects.prefetch_related(
            'items__inventory_item__store'
        ).get_or_create(user=request.user)
        
        cart_store = cart.store
        
        # --- START MODIFIED LOGIC ---
        
        if cart_store and cart_store != inventory_item.store:
            # Badlaav yahaan hai. Hum 400 ke bajaye 409 CONFLICT bhej rahe hain.
            # Hum frontend ko batane ke liye data bhi bhej rahe hain.
            return Response(
                {
                    "code": "STORE_CONFLICT",
                    "error": (
                        f"Aap sirf '{cart_store.name}' store se hi items add kar sakte hain. "
                        "Naye store se order karne ke liye pehle cart khaali karein."
                    ),
                    "current_store": {
                        "id": cart_store.id,
                        "name": cart_store.name
                    },
                    "new_store": {
                        "id": inventory_item.store.id,
                        "name": inventory_item.store.name
                    }
                },
                status=status.HTTP_409_CONFLICT # <-- Status code badal gaya
            )
        
        # --- END MODIFIED LOGIC ---
        
        with transaction.atomic():
            try:
                locked_inventory_item = StoreInventory.objects.select_for_update().get(id=inventory_item_id)
            except StoreInventory.DoesNotExist:
                 return Response({"error": "Item not found."}, status=status.HTTP_404_NOT_FOUND)

            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                inventory_item=locked_inventory_item, 
                defaults={'quantity': 0}
            )
            
            new_quantity = cart_item.quantity + quantity_to_add
            
            if locked_inventory_item.stock_quantity < new_quantity:
                
                if created:
                    cart_item.delete()
                
                return Response(
                    {"error": f"Not enough stock for {locked_inventory_item.variant.product.name}. "
                              f"Only {locked_inventory_item.stock_quantity} available."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            cart_item.quantity = new_quantity
            cart_item.save()

        optimized_cart = Cart.objects.prefetch_related(
            'items__inventory_item__variant__product__category',
            'items__inventory_item__store',
            'store'
        ).get(id=cart.id)
        
        cart_serializer = CartSerializer(optimized_cart, context={'request': request})
        return Response(cart_serializer.data, status=status.HTTP_200_OK)

class CartItemUpdateView(generics.GenericAPIView):
    """
    API endpoint: PATCH /api/cart/item/<int:pk>/update/
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = CartItemUpdateSerializer

    def patch(self, request, *args, **kwargs):
        cart_item_id = self.kwargs.get('pk')
        
        try:
            cart_item = CartItem.objects.get(
                id=cart_item_id, 
                cart__user=request.user
            )
        except CartItem.DoesNotExist:
            return Response({"error": "Cart item not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        new_quantity = serializer.validated_data['quantity']
        
        if new_quantity == 0:
            cart_item.delete()
            optimized_cart = Cart.objects.prefetch_related(
                'items__inventory_item__variant__product__category',
                'items__inventory_item__store',
                'store'
            ).get(user=request.user)
            cart_serializer = CartSerializer(optimized_cart, context={'request': request})
            return Response(cart_serializer.data, status=status.HTTP_200_OK)

   
        with transaction.atomic():
            try:
                locked_inventory_item = StoreInventory.objects.select_for_update().get(
                    id=cart_item.inventory_item.id
                )
            except StoreInventory.DoesNotExist:
                return Response({"error": "Item not found."}, status=status.HTTP_404_NOT_FOUND)

            if locked_inventory_item.stock_quantity < new_quantity:
                return Response(
                    {"error": f"Not enough stock. Only {locked_inventory_item.stock_quantity} available."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            cart_item.quantity = new_quantity
            cart_item.save()
  
        optimized_cart = Cart.objects.prefetch_related(
            'items__inventory_item__variant__product__category',
            'items__inventory_item__store',
            'store'
        ).get(id=cart_item.cart.id)
        cart_serializer = CartSerializer(optimized_cart, context={'request': request})
        return Response(cart_serializer.data, status=status.HTTP_200_OK)


class CartItemRemoveView(generics.DestroyAPIView):
    """
    (UPDATED with prefetch for optimization)
    """
    permission_classes = [IsAuthenticated, IsCustomer]

    def get_queryset(self):
        return CartItem.objects.filter(cart__user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        
        cart = Cart.objects.prefetch_related(
            'items__inventory_item__variant__product__category',
            'items__inventory_item__store',
            'store'
        ).get(user=request.user)
        
        cart_serializer = CartSerializer(cart, context={'request': request})
        # 204 (No Content) ke bajaye 200 (OK) aur updated cart bhejna behtar hai
        return Response(cart_serializer.data, status=status.HTTP_200_OK)


# --- NAYA VIEW ---
class CartClearView(generics.GenericAPIView):
    """
    API endpoint: DELETE /api/cart/clear/
    User ke cart se sabhi items ko delete kar deta hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = CartSerializer

    def delete(self, request, *args, **kwargs):
        # User ka cart dhoondein (ya banayein, agar nahi hai)
        cart, created = Cart.objects.get_or_create(user=self.request.user)
        
        if not created and cart.items.exists():
            # Agar cart hai aur usmein items hain, toh unhe delete karein
            cart.items.all().delete()
            logger.info(f"Cart cleared for user {request.user.username}") # <-- CHANGED
        
        # Optimized cart response (khaali cart)
        optimized_cart = Cart.objects.prefetch_related(
            'store' # Store None hoga, lekin prefetch safe hai
        ).get(id=cart.id)
        
        serializer = self.get_serializer(optimized_cart, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
# --- END NAYA VIEW ---