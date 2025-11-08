# orders/views.py (Feature 4: Rider Tip ke saath fully updated)

from django.db import transaction
from django.db.models import F
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny 
from django.views.decorators.csrf import csrf_exempt 
from django.utils.decorators import method_decorator
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from delivery.serializers import RiderDeliverySerializer 
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.contrib.gis.measure import Distance 
import razorpay 

# Model Imports
from .models import Order, OrderItem, Payment, Address, Coupon
from cart.models import Cart
from inventory.models import StoreInventory
from delivery.models import Delivery 

# Serializer Imports
from .serializers import (
    CheckoutSerializer, 
    OrderDetailSerializer, 
    OrderHistorySerializer,
    PaymentVerificationSerializer
)
# Permission Imports
from accounts.permissions import IsCustomer 


def process_successful_payment(order_id):
    """
    Ek PENDING order ko CONFIRMED banata hai.
    (Stock cut, Delivery create, Cart delete, Coupon use count update)
    """
    
    try:
        order = Order.objects.get(order_id=order_id, status=Order.OrderStatus.PENDING)
    except Order.DoesNotExist:
        return False, "Order not found or already processed."

    try:
        with transaction.atomic():
            order_lock = Order.objects.select_for_update().get(pk=order.pk)
            
            cart = Cart.objects.get(user=order.user)
            cart_items = cart.items.all()

            inventory_items_to_update = []
            for item in cart_items:
                inv_item = StoreInventory.objects.select_for_update().get(id=item.inventory_item.id)
                if inv_item.stock_quantity < item.quantity:
                    raise Exception(f"Item '{inv_item.variant.product.name}' is out of stock.")
                
                inv_item.stock_quantity = F('stock_quantity') - item.quantity
                inventory_items_to_update.append(inv_item)

            StoreInventory.objects.bulk_update(inventory_items_to_update, ['stock_quantity'])

            # Coupon usage count update karein
            if order_lock.coupon:
                coupon = Coupon.objects.select_for_update().get(id=order_lock.coupon.id)
                coupon.times_used = F('times_used') + 1
                coupon.save(update_fields=['times_used'])

            # Payment status update karein
            payment = order.payments.first()
            if payment:
                payment.status = Order.PaymentStatus.SUCCESSFUL
                payment.save()
            
            # Order status update karein
            order_lock.status = Order.OrderStatus.CONFIRMED
            order_lock.payment_status = Order.PaymentStatus.SUCCESSFUL
            order_lock.save()
            
            # Delivery create karein
            delivery = Delivery.objects.create(order=order_lock)

            # Cart delete karein
            cart.items.all().delete()
            
            return True, delivery

    except Exception as e:
        order.status = Order.OrderStatus.FAILED
        order.payment_status = Order.PaymentStatus.FAILED
        order.save()
        
        payment = order.payments.first()
        if payment:
            payment.status = Order.PaymentStatus.FAILED
            payment.save()
        
        return False, str(e) 


class CheckoutView(generics.GenericAPIView):
    """
    --- UPDATED ---
    Checkout view ab COD, Razorpay, Coupons, aur Rider Tips ko handle karta hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = CheckoutSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        validated_data = serializer.validated_data
        
        payment_method = validated_data.get('payment_method', 'RAZORPAY')
        coupon = validated_data.get('coupon_code') 
        
        # --- RIDER TIP LOGIC ---
        rider_tip = validated_data.get('rider_tip', Decimal('0.00'))
        # --- END RIDER TIP ---

        try:
            cart = Cart.objects.get(user=user)
        except Cart.DoesNotExist:
            return Response({"error": "Cart not found."}, status=status.HTTP_404_NOT_FOUND)

        if not cart.items.exists():
            return Response({"error": "Your cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

        cart_items = cart.items.all()
        store = cart.store
        address = Address.objects.get(id=validated_data['delivery_address_id'], user=user)

        # --- NAYA CALCULATION LOGIC (WITH TIP) ---
        
        # 1. Cart ka subtotal
        item_subtotal = cart.total_price
        
        # 2. Coupon discount
        discount_amount = Decimal('0.00')
        if coupon:
            is_valid, message = coupon.is_valid(item_subtotal)
            if not is_valid:
                return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)
            discount_amount = coupon.calculate_discount(item_subtotal)
        
        # 3. Discounted subtotal
        subtotal_after_discount = (item_subtotal - discount_amount)
        
        # 4. Delivery fee
        delivery_fee = Decimal('0.00')
        try:
            if store.location and address.location:
                distance_km = Distance(store.location, address.location).km
                base_fee = settings.BASE_DELIVERY_FEE
                fee_per_km = settings.FEE_PER_KM
                delivery_fee = base_fee + (Decimal(distance_km) * fee_per_km)
                delivery_fee = min(delivery_fee, settings.MAX_DELIVERY_FEE)
                delivery_fee = max(delivery_fee, settings.MIN_DELIVERY_FEE)
            else:
                delivery_fee = settings.MIN_DELIVERY_FEE
        except AttributeError:
            delivery_fee = Decimal('20.00') 
            print("Warning: Delivery fee settings not found in settings.py. Using default 20.00")

        # 5. Tax (Discounted price par)
        tax_rate = getattr(settings, 'TAX_RATE', Decimal('0.05')) # 5% default
        taxes_amount = (subtotal_after_discount * tax_rate).quantize(Decimal('0.01'))
        
        # 6. Final Total (Tip ko yahaan jodein)
        final_total = (
            subtotal_after_discount + 
            delivery_fee + 
            taxes_amount + 
            rider_tip  # <-- Tip ko total mein joda gaya
        ).quantize(Decimal('0.01'))
        
        if final_total < 0:
            final_total = Decimal('0.00')
            
        final_total_paise = int(final_total * 100)
        # --- End Calculation ---

        # Step 1: Django mein PENDING Order banayein
        try:
            order = Order.objects.create(
                user=user,
                store=store,
                delivery_address=address,
                item_subtotal=item_subtotal,
                delivery_fee=delivery_fee,
                taxes_amount=taxes_amount,
                coupon=coupon,
                discount_amount=discount_amount,
                rider_tip=rider_tip,             # <-- Tip ko save karein
                final_total=final_total,
                special_instructions=validated_data.get('special_instructions', ''),
                status=Order.OrderStatus.PENDING, 
                payment_status=Order.PaymentStatus.PENDING
            )

            # OrderItems banayein
            order_items_to_create = []
            for item in cart_items:
                order_items_to_create.append(
                    OrderItem(
                        order=order,
                        inventory_item=item.inventory_item,
                        product_name=item.inventory_item.variant.product.name,
                        variant_name=item.inventory_item.variant.variant_name,
                        price_at_order=item.inventory_item.get_current_price,
                        quantity=item.quantity
                    )
                )
            OrderItem.objects.bulk_create(order_items_to_create)

        except Exception as e:
            return Response(
                {"error": f"Order creation (Step 1) failed: {str(e)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        
        # Step 2: Payment Method ke aadhar par logic alag karein
        
        # ==================
        #  IF PAYMENT = COD
        # ==================
        if payment_method == 'COD':
            try:
                Payment.objects.create(
                    order=order,
                    payment_method='COD',
                    amount=final_total, # <-- Yeh ab tip-included total hai
                    status=Order.PaymentStatus.PENDING,
                    transaction_id=f"cod_{order.order_id}"
                )
                
                success, result = process_successful_payment(order.order_id)
                
                if not success:
                    return Response({"error": f"Failed to process COD order: {result}"}, status=status.HTTP_400_BAD_REQUEST)
                
                order_serializer = OrderDetailSerializer(order, context={'request': request})
                return Response({
                    "message": "COD Order confirmed successfully.",
                    "order_details": order_serializer.data
                }, status=status.HTTP_201_CREATED)

            except Exception as e:
                order.status = Order.OrderStatus.FAILED
                order.payment_status = Order.PaymentStatus.FAILED
                order.save()
                return Response(
                    {"error": f"COD Order processing failed: {str(e)}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ======================
        #  IF PAYMENT = RAZORPAY
        # ======================
        elif payment_method == 'RAZORPAY':
            
            # --- Agar order FREE hai ---
            if final_total_paise <= 0: # 0 ya usse kam
                try:
                    Payment.objects.create(
                        order=order,
                        payment_method='RAZORPAY', # Ya 'FREE'
                        amount=0.00,
                        status=Order.PaymentStatus.PENDING,
                        transaction_id=f"free_{order.order_id}"
                    )
                    success, result = process_successful_payment(order.order_id)
                    
                    if not success:
                         return Response({"error": f"Failed to process free order: {result}"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    order_serializer = OrderDetailSerializer(order, context={'request': request})
                    return Response({
                        "message": "Free order confirmed successfully.",
                        "order_details": order_serializer.data
                    }, status=status.HTTP_201_CREATED)
                except Exception as e:
                     order.status = Order.OrderStatus.FAILED
                     order.payment_status = Order.PaymentStatus.FAILED
                     order.save()
                     return Response({"error": f"Free order processing failed: {str(e)}"}, status=HTTP_400_BAD_REQUEST)
            
            # --- Standard Razorpay flow (agar payment zaroori hai) ---
            try:
                client = razorpay.Client(
                    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
                )
                
                razorpay_order_data = {
                    'amount': final_total_paise, # <-- Yeh ab tip-included amount hai
                    'currency': 'INR',
                    'receipt': order.order_id,
                    'notes': {'django_order_id': order.order_id}
                }
                razorpay_order = client.order.create(data=razorpay_order_data)

                Payment.objects.create(
                    order=order,
                    payment_method='RAZORPAY',
                    amount=final_total, # <-- Yeh ab tip-included amount hai
                    status=Order.PaymentStatus.PENDING,
                    razorpay_order_id=razorpay_order['id'],
                    transaction_id=f"pending_{order.order_id}"
                )
                
                return Response({
                    "message": "Order created, awaiting payment.",
                    "razorpay_key": settings.RAZORPAY_KEY_ID,
                    "razorpay_order_id": razorpay_order['id'],
                    "amount": final_total_paise,
                    "currency": "INR",
                    "django_order_id": order.order_id,
                }, status=status.HTTP_201_CREATED)

            except Exception as e:
                if 'order' in locals():
                    order.status = Order.OrderStatus.FAILED
                    order.payment_status = Order.PaymentStatus.FAILED
                    order.save()
                return Response(
                    {"error": f"Razorpay order creation failed: {str(e)}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        else:
            return Response(
                {"error": f"Payment method '{payment_method}' is not supported."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    
@method_decorator(csrf_exempt, name='dispatch')
class PaymentVerificationView(generics.GenericAPIView):
    """
    (Aapka code - Ismein koi badlaav nahi hai)
    """
    permission_classes = [IsAuthenticated, IsCustomer] 
    serializer_class = PaymentVerificationSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            payment = Payment.objects.get(
                razorpay_order_id=data['razorpay_order_id'],
                order__user=request.user, 
                status=Order.PaymentStatus.PENDING
            )
            order = payment.order
        
        except Payment.DoesNotExist:
            return Response(
                {"error": "Invalid order ID or payment already processed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': data['razorpay_order_id'],
                'razorpay_payment_id': data['razorpay_payment_id'],
                'razorpay_signature': data['razorpay_signature']
            })
            
            payment.transaction_id = data['razorpay_payment_id'] 
            payment.save() 

            success, result = process_successful_payment(order.order_id)
            
            if success:
                order_serializer = OrderDetailSerializer(order, context={'request': request})
                return Response(
                    {"success": "Payment successful, order confirmed.", "order": order_serializer.data},
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {"error": f"Payment verified but failed to process order: {result}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        except razorpay.errors.SignatureVerificationError as e:
            payment.status = Order.PaymentStatus.FAILED
            order.status = Order.OrderStatus.FAILED
            order.payment_status = Order.PaymentStatus.FAILED
            payment.save()
            order.save()
            
            return Response(
                {"error": "Payment verification failed. Invalid signature."},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"error": f"An unexpected error occurred: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class OrderHistoryView(generics.ListAPIView):
    """
    (Aapka code - Ismein koi badlaav nahi hai)
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = OrderHistorySerializer

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).select_related('store').order_by('-created_at')


class OrderDetailView(generics.RetrieveAPIView):
    """
    (Aapka code - Ismein koi badlaav nahi hai)
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = OrderDetailSerializer
    lookup_field = 'order_id' 

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related(
            'items', 
            'payments'
        ).select_related('store', 'delivery_address', 'delivery', 'coupon')


class OrderCancelView(generics.GenericAPIView):
    """
    API: POST /api/orders/<order_id>/cancel/
    (Aapka code - Ismein koi badlaav nahi hai)
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = OrderDetailSerializer

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        order_id = self.kwargs.get('order_id')
        try:
            order = Order.objects.select_for_update().get(
                order_id=order_id,
                user=request.user
            )
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        if order.status not in [Order.OrderStatus.PENDING, Order.OrderStatus.CONFIRMED]:
            return Response(
                {"error": f"Order in status '{order.status}' cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if order.status == Order.OrderStatus.CONFIRMED:
            confirmation_time = order.updated_at 
            if (timezone.now() - confirmation_time).total_seconds() > 300: # 5 minutes
                return Response(
                    {"error": "Confirmed orders can only be cancelled within 5 minutes."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        original_status = order.status
        
        order.status = Order.OrderStatus.CANCELLED
        
        if order.payment_status == Order.PaymentStatus.SUCCESSFUL:
            order.payment_status = Order.PaymentStatus.REFUNDED
            print(f"Triggering refund for Order {order.order_id}")
        
        order.save()

        try:
            delivery = Delivery.objects.select_for_update().get(order=order)
            
            if delivery.status in [
                Delivery.DeliveryStatus.PICKED_UP,
                Delivery.DeliveryStatus.DELIVERED
            ]:
                raise Exception(f"Cannot cancel, delivery is already {delivery.status}")

            delivery.status = Delivery.DeliveryStatus.CANCELLED
            delivery.save()

        except Delivery.DoesNotExist:
            pass
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if original_status == Order.OrderStatus.CONFIRMED:
            order_items = order.items.all()
            inventory_items_to_update = []
            
            for item in order_items:
                if item.inventory_item:
                    try:
                        inv_item = StoreInventory.objects.select_for_update().get(id=item.inventory_item.id)
                        inv_item.stock_quantity = F('stock_quantity') + item.quantity
                        inventory_items_to_update.append(inv_item)
                        
                    except StoreInventory.DoesNotExist:
                        print(f"Warning: Inventory item {item.inventory_item.id} not found during stock revert.")
            
            if inventory_items_to_update:
                StoreInventory.objects.bulk_update(inventory_items_to_update, ['stock_quantity'])
                print(f"Stock reverted for {len(inventory_items_to_update)} items.")

        serializer = self.get_serializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)