import logging # <-- ADD
from django.db import transaction
from django.db.models import F, Avg
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny 
from django.views.decorators.csrf import csrf_exempt 
from django.utils.decorators import method_decorator
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from django.contrib.gis.measure import Distance 
import razorpay 
import json         
import hmac         
import hashlib      
from rest_framework.views import APIView 
# from orders.models import OrderItem # <-- REMOVED (Duplicate)

# Task Imports
# (Guarded imports ko neeche functions mein move kar diya gaya hai)
from .tasks import process_razorpay_refund_task

# Model Imports
from .models import Order, OrderItem, Payment, Address, Coupon
from cart.models import Cart, CartItem
from inventory.models import StoreInventory
from delivery.models import Delivery 

# Serializer Imports
from delivery.serializers import RiderDeliverySerializer 
from cart.serializers import CartSerializer
from .serializers import (
    CheckoutSerializer, 
    OrderDetailSerializer, 
    OrderHistorySerializer,
    PaymentVerificationSerializer,
    RiderRatingSerializer
)
# Permission Imports
from accounts.permissions import IsCustomer 

# Setup logger
logger = logging.getLogger(__name__) # <-- ADD


def process_successful_payment(order_id):
    """
    Ek PENDING order ko CONFIRMED banata hai.
    (Stock cut, Delivery create, Coupon use count update)
    --- AB YEH WMS PICK TASKS BHI BANATA HAI ---
    """
    # --- GUARDED IMPORTS (Circular dependency se bachne ke liye) ---
    from wms.models import WmsStock, PickTask
    from accounts.models import StoreStaffProfile
    # --- END GUARDED IMPORTS ---

    try:
        # Order aur uske items ko pehle hi fetch kar lein
        order = Order.objects.prefetch_related('items').get(
            order_id=order_id, 
            status=Order.OrderStatus.PENDING
        )
    except Order.DoesNotExist:
        logger.warning(f"process_successful_payment: Order {order_id} not found or already processed.") # <-- ADDED
        return False, "Order not found or already processed."

    try:
        with transaction.atomic():
            order_lock = Order.objects.select_for_update().get(pk=order.pk)

            # Cart se items lene ke bajaye, ab hum order se items lenge
            order_items = order_lock.items.all()

            # Check karein ki cart (ya order) khaali na ho
            if not order_items.exists():
                 raise Exception("Order has no items to process.")

            # Stock cut logic (yeh pehle se tha)
            # inventory_items_to_update = []
            for item in order_items:
                # Note: YEH ABHI BHI SUMMARY (StoreInventory) SE STOCK CUT KAR RAHA HAI
                # WMS ke baad, yeh logic badalna chahiye,
                # lekin abhi ke liye ise chhod dete hain taaki cart flow na toote.
                # Asal stock 'WmsStock' se PickTaskCompleteView mein katega.

                # Hum WMS flow ke liye stock check ko skip kar sakte hain,
                # ya WmsStock summary par bharosa kar sakte hain.
                
                # --- FIX: Humne summary stock check (extra DB query) ko hata diya hai ---
                # (Pichle turn mein yeh fix apply kiya gaya tha, use rakha gaya hai)
                # inv_item = StoreInventory.objects.select_for_update().get(id=item.inventory_item.id)
                # if inv_item.stock_quantity < item.quantity:
                #    raise Exception(f"Item '{inv_item.variant.product.name}' is out of stock (Summary).")
                # --- END FIX ---

                # Yeh summary stock hai, WMS granular stock se alag hai.
                # Hum isse update NAHI karenge, taaki WMS par control rahe.

                # inv_item.stock_quantity = F('stock_quantity') - item.quantity
                # inventory_items_to_update.append(inv_item)

                pass # Stock cutting ko WMS par chhod dein

            # StoreInventory.objects.bulk_update(inventory_items_to_update, ['stock_quantity'])

            # Coupon usage count update karein (yeh pehle se tha)
            if order_lock.coupon:
                coupon = Coupon.objects.select_for_update().get(id=order_lock.coupon.id)
                coupon.times_used = F('times_used') + 1
                coupon.save(update_fields=['times_used'])

            # Payment status update karein (yeh pehle se tha)
            payment = order.payments.first()
            if payment:
                payment.status = Order.PaymentStatus.SUCCESSFUL
                payment.save()

            # Order status update karein (yeh pehle se tha)
            order_lock.status = Order.OrderStatus.CONFIRMED
            order_lock.payment_status = Order.PaymentStatus.SUCCESSFUL
            order_lock.save()

            # Delivery create karein (yeh pehle se tha)
            delivery = Delivery.objects.create(order=order_lock) # Status default AWAITING_PREPARATION hoga

            # Cart delete karein (yeh pehle se tha)
            try:
                cart = Cart.objects.get(user=order.user)
                cart.items.all().delete()
            except Cart.DoesNotExist:
                pass # Agar cart pehle hi delete ho gaya ho

            # --- NAYA WMS LOGIC START ---

            # 1. Store ke liye ek available picker dhoondein
            picker_user = None
            staff_profile = StoreStaffProfile.objects.filter(
                store=order_lock.store,
                can_pick_orders=True
            ).order_by(
                    'last_task_assigned_at' # NULLs first, fir sabse purana
            ).first() # Design doc ke mutabik, pehla available picker

            if staff_profile:
                picker_user = staff_profile.user
                    
                # ZAROORI: Ab is picker ka timestamp update karein
                staff_profile.last_task_assigned_at = timezone.now()
                staff_profile.save(update_fields=['last_task_assigned_at'])
                    
                logger.info(f"Assigning PickTasks for Order {order_id} to Picker {picker_user.username} (Round-Robin)") # <-- CHANGED
            else:
                logger.warning(f"WARNING: Order {order_id} ke liye koi available picker (can_pick_orders=True) nahi mila.") # <-- CHANGED

            tasks_created = 0

            # 2. Har OrderItem ke liye PickTask banayein
            for item in order_items:
                inventory_item = item.inventory_item
                quantity_to_pick = item.quantity # Hum is variable ko update karenge

                # Pehle, summary stock check karein (jo WMS signal se sync hota hai)
                # Hum transaction ke andar hain, isliye get() ka istemaal sahi hai
                inv_summary_check = StoreInventory.objects.get(id=inventory_item.id)
                
                if inv_summary_check.stock_quantity < quantity_to_pick:
                    # Agar summary stock hi nahi hai, toh fail karein
                    raise Exception(f"Item '{inventory_item.variant.product.name}' (SKU: {inventory_item.variant.sku}) is out of stock (Summary). Needed {quantity_to_pick}, found {inv_summary_check.stock_quantity}.")

                # --- NAYA "Greedy" Stock Splitting Logic ---
                
                # WmsStock locations dhoondein jahaan stock hai
                available_stock_locations = WmsStock.objects.filter(
                    inventory_summary=inventory_item,
                    quantity__gt=0
                ).select_related('location').order_by('location__code') # Picker ki efficiency ke liye location code se sort karein

                pick_tasks_to_create = [] # Is item ke liye tasks list

                for stock_loc in available_stock_locations:
                    if quantity_to_pick <= 0:
                        break # Humne zaroori quantity poori kar li

                    # Is location se kitna uthana hai
                    quantity_from_this_loc = min(stock_loc.quantity, quantity_to_pick)
                    
                    # PickTask (memory mein) banayein
                    task = PickTask(
                        order=order_lock,
                        location=stock_loc.location,
                        variant=inventory_item.variant,
                        quantity_to_pick=quantity_from_this_loc,
                        assigned_to=picker_user,
                        status=PickTask.PickStatus.PENDING
                    )
                    pick_tasks_to_create.append(task)
                    
                    # Zaroori quantity ko kam karein
                    quantity_to_pick -= quantity_from_this_loc
                
                # --- End Greedy Logic ---

                # 3. Check karein ki poora stock mila ya nahi
                if quantity_to_pick > 0:
                    # CRITICAL: Summary stock (e.g., 10) aur granular stock (e.g., total 8) out of sync hain!
                    # Transaction ko rollback karna zaroori hai.
                    logger.critical(f"CRITICAL SYNC ERROR: Order {order_id} - Item {inventory_item.variant.sku} (Qty: {item.quantity}).") # <-- CHANGED
                    logger.critical(f"Summary stock was {inv_summary_check.stock_quantity}, but granular stock only had {item.quantity - quantity_to_pick} available.") # <-- CHANGED
                    raise Exception(f"Stock sync error for {inventory_item.variant.sku}. Could not fulfill order. Please audit stock.")
                
                else:
                    # Sab theek hai, tasks ko bulk create karein (performance ke liye)
                    PickTask.objects.bulk_create(pick_tasks_to_create)
                    tasks_created += len(pick_tasks_to_create)

            logger.info(f"WMS: Created {tasks_created} PickTasks for Order {order_id}") # <-- CHANGED
            # --- NAYA WMS LOGIC END ---


        return True, delivery

    except Exception as e:
        logger.error(f"process_successful_payment for {order_id} FAILED: {e}") # <-- ADDED
        order.status = Order.OrderStatus.FAILED
        order.payment_status = Order.PaymentStatus.FAILED
        order.save()

        payment = order.payments.first()
        if payment:
            payment.status = Order.PaymentStatus.FAILED
            payment.save()

        return False, str(e) 

# ... (Baaqi views jaise CheckoutView, PaymentVerificationView, etc. waise hi rahenge) ...



# File: orders/views.py

# ... (all your existing imports like logging, transaction, settings, models, etc.) ...
# Make sure Decimal is imported from decimal
from decimal import Decimal

# ... (process_successful_payment function remains the same as our last update) ...


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
        rider_tip = validated_data.get('rider_tip', Decimal('0.00'))

        try:
            cart = Cart.objects.get(user=user)
        except Cart.DoesNotExist:
            return Response({"error": "Cart not found."}, status=status.HTTP_404_NOT_FOUND)

        if not cart.items.exists():
            return Response({"error": "Your cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

        cart_items = cart.items.all()
        store = cart.store
        address = Address.objects.get(id=validated_data['delivery_address_id'], user=user)

        # --- REFACTORED CALCULATION LOGIC ---
        
        # 1. Cart ka subtotal (yeh humein cart se chahiye)
        item_subtotal = cart.total_price
        
        # 2. Coupon validation (Order create karne se pehle check karna zaroori hai)
        if coupon:
            is_valid, message = coupon.is_valid(item_subtotal)
            if not is_valid:
                # Agar coupon invalid hai (e.g., min purchase), toh fail karein
                return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)
        
        # 3. Delivery fee (yeh bhi pehle calculate karna zaroori hai)
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
            logger.warning("Delivery fee settings not found in settings.py. Using default 20.00")

        # --- BAAKI SABHI CALCULATIONS (DISCOUNT, TAX, FINAL TOTAL) YAHAN SE HATA DIYE GAYE HAIN ---
        
        # --- End Refactored Calculation ---

        # Step 1: Django mein PENDING Order banayein
        try:
            order = Order.objects.create(
                user=user,
                store=store,
                delivery_address=address,
                item_subtotal=item_subtotal,     # <-- Humara calculated subtotal
                delivery_fee=delivery_fee,      # <-- Humari calculated delivery fee
                taxes_amount=Decimal('0.00'),   # <-- Default, model calculate karega
                coupon=coupon,                  # <-- Validated coupon
                discount_amount=Decimal('0.00'),# <-- Default, model calculate karega
                rider_tip=rider_tip,            # <-- User ka tip
                final_total=Decimal('0.00'),    # <-- Default, model calculate karega
                special_instructions=validated_data.get('special_instructions', ''),
                status=Order.OrderStatus.PENDING, 
                payment_status=Order.PaymentStatus.PENDING
            )

            # OrderItems banayein
            # YEH ZAROORI HAI: recalculate_totals() se pehle items order se link hone chahiye
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
            
            # --- CHANGE: Call the new centralized method ---
            # Yeh method ab subtotal, discount, tax, aur final total
            # ko calculate karke order par SAVE karega.
            order.recalculate_totals(save=True)
            # --- END CHANGE ---

        except Exception as e:
            logger.error(f"Checkout (Step 1 - Order Creation) failed for user {user.username}: {e}") # <-- ADDED
            return Response(
                {"error": f"Order creation (Step 1) failed: {str(e)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        
        # --- CHANGE: Final total ko order se dobara padhein ---
        # Ab yeh hamesha model se match karega
        final_total_paise = int(order.final_total * 100)
        # --- END CHANGE ---
        
        # Step 2: Payment Method ke aadhar par logic alag karein
        
        # ==================
        #  IF PAYMENT = COD
        # ==================
        if payment_method == 'COD':
            try:
                Payment.objects.create(
                    order=order,
                    payment_method='COD',
                    amount=order.final_total, # <-- Refactored total
                    status=Order.PaymentStatus.PENDING,
                    transaction_id=f"cod_{order.order_id}"
                )
                
                success, result = process_successful_payment(order.order_id)
                
                if not success:
                    logger.error(f"Checkout (COD) failed for order {order.order_id} during process_successful_payment: {result}") # <-- ADDED
                    return Response({"error": f"Failed to process COD order: {result}"}, status=status.HTTP_400_BAD_REQUEST)
                
                order_serializer = OrderDetailSerializer(order, context={'request': request})
                return Response({
                    "message": "COD Order confirmed successfully.",
                    "order_details": order_serializer.data
                }, status=status.HTTP_201_CREATED)

            except Exception as e:
                logger.error(f"Checkout (COD) exception for order {order.order_id}: {e}") # <-- ADDED
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
                         logger.error(f"Checkout (Free Order) failed for order {order.order_id}: {result}") # <-- ADDED
                         return Response({"error": f"Failed to process free order: {result}"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    order_serializer = OrderDetailSerializer(order, context={'request': request})
                    return Response({
                        "message": "Free order confirmed successfully.",
                        "order_details": order_serializer.data
                    }, status=status.HTTP_201_CREATED)
                except Exception as e:
                     logger.error(f"Checkout (Free Order) exception for order {order.order_id}: {e}") # <-- ADDED
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
                    'amount': final_total_paise, # <-- Refactored total
                    'currency': 'INR',
                    'receipt': order.order_id,
                    'notes': {'django_order_id': order.order_id}
                }
                razorpay_order = client.order.create(data=razorpay_order_data)

                Payment.objects.create(
                    order=order,
                    payment_method='RAZORPAY',
                    amount=order.final_total, # <-- Refactored total
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
                logger.error(f"Checkout (Razorpay Order Create) exception for django_order {order.order_id}: {e}") # <-- ADDED
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
                logger.error(f"PaymentVerificationView: Payment verified but failed to process order {order.order_id}: {result}") # <-- ADDED
                return Response(
                    {"error": f"Payment verified but failed to process order: {result}"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )

        except razorpay.errors.SignatureVerificationError as e:
            logger.warning(f"PaymentVerificationView: SignatureVerificationError for RZP order {data['razorpay_order_id']}: {e}") # <-- ADDED
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
            logger.error(f"PaymentVerificationView: Unexpected error for RZP order {data['razorpay_order_id']}: {e}") # <-- ADDED
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
    (UPDATED with WMS Stock Revert Logic)
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = OrderDetailSerializer

    def post(self, request, *args, **kwargs):
        # --- GUARDED IMPORTS (Circular dependency se bachne ke liye) ---
        from wms.models import WmsStock, PickTask
        # --- END GUARDED IMPORTS ---
        
        order_id = self.kwargs.get('order_id')
        try:
            order = Order.objects.get(
                order_id=order_id,
                user=request.user
            )
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        # 1. Check karein ki order cancel ho sakta hai ya nahi
        if order.status not in [Order.OrderStatus.PENDING, Order.OrderStatus.CONFIRMED, Order.OrderStatus.PREPARING]:
            return Response(
                {"error": f"Order in status '{order.status}' cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 2. Time window check karein (Sirf CONFIRMED/PREPARING par)
        if order.status in [Order.OrderStatus.CONFIRMED, Order.OrderStatus.PREPARING]:
            confirmation_time = order.updated_at 
            if (timezone.now() - confirmation_time).total_seconds() > getattr(settings, 'ORDER_CANCELLATION_WINDOW', 300): 
                return Response(
                    {"error": f"Confirmed orders can only be cancelled within {getattr(settings, 'ORDER_CANCELLATION_WINDOW', 300) // 60} minutes."},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        original_status = order.status
        payment_to_refund = None
        
        # 3. Database operations ko transaction mein daalein
        try:
            with transaction.atomic():
                # Order ko lock karein
                order_lock = Order.objects.select_for_update().get(pk=order.id)
                
                # Payment ko check karein
                if order_lock.payment_status == Order.PaymentStatus.SUCCESSFUL:
                    payment = order_lock.payments.filter(
                        status=Order.PaymentStatus.SUCCESSFUL,
                        payment_method='RAZORPAY'
                    ).first()
                    
                    if payment and payment.transaction_id:
                        payment_to_refund = payment
                        payment.status = Order.PaymentStatus.REFUND_INITIATED
                        payment.save(update_fields=['status'])
                        order_lock.payment_status = Order.PaymentStatus.REFUND_INITIATED
                    else:
                        order_lock.payment_status = Order.PaymentStatus.REFUNDED
                
                # Order ko CANCELLED set karein
                order_lock.status = Order.OrderStatus.CANCELLED
                order_lock.save(update_fields=['status', 'payment_status']) 

                # Delivery ko cancel karein
                try:
                    delivery = Delivery.objects.select_for_update().get(order=order_lock)
                    if delivery.status in [Delivery.DeliveryStatus.PICKED_UP, Delivery.DeliveryStatus.DELIVERED]:
                        raise Exception(f"Cannot cancel, delivery is already {delivery.status}")
                    
                    delivery.status = Delivery.DeliveryStatus.CANCELLED
                    delivery.save(update_fields=['status'])
                except Delivery.DoesNotExist:
                    pass 

                # --- NAYA "SUPERB" WMS STOCK REVERT LOGIC ---
                # Hum 'StoreInventory' ko direct touch nahi karenge
                
                # Agar order CONFIRMED ya PREPARING tha, tabhi stock revert hoga
                if original_status in [Order.OrderStatus.CONFIRMED, Order.OrderStatus.PREPARING]:
                    
                    # 1. Saare PENDING PickTasks ko CANCELLED mark karein
                    pending_tasks = PickTask.objects.filter(
                        order=order_lock,
                        status=PickTask.PickStatus.PENDING
                    )
                    updated_tasks_count = pending_tasks.update(status=PickTask.PickStatus.CANCELLED)
                    logger.info(f"Cancelled {updated_tasks_count} pending pick tasks for order {order.order_id}.") # <-- CHANGED

                    # 2. Jo tasks COMPLETED ho chuke hain, unka stock WMS mein wapas add karein
                    completed_tasks = PickTask.objects.filter(
                        order=order_lock,
                        status=PickTask.PickStatus.COMPLETED
                    )
                    
                    if completed_tasks.exists():
                        stocks_to_update = {} # Dictionary {wms_stock_id: quantity_to_add}
                        
                        for task in completed_tasks:
                            try:
                                stock_item = WmsStock.objects.select_for_update().get(
                                    inventory_summary__variant=task.variant,
                                    location=task.location
                                )
                                if stock_item.id not in stocks_to_update:
                                    stocks_to_update[stock_item.id] = 0
                                stocks_to_update[stock_item.id] += task.quantity_to_pick
                            
                            except WmsStock.DoesNotExist:
                                 logger.warning(f"Warning: Stock revert karte waqt WMS stock for task {task.id} nahi mila.") # <-- CHANGED

                        # Ab stock ko bulk update karein (F() expression ke saath)
                        if stocks_to_update:
                            for stock_id, qty in stocks_to_update.items():
                                WmsStock.objects.filter(id=stock_id).update(quantity=F('quantity') + qty)
                            logger.info(f"Reverted stock for {len(stocks_to_update)} WMS locations for order {order.order_id}.") # <-- CHANGED
                            # WmsStock ka signal StoreInventory summary ko automatically fix kar dega
                
                # --- END NAYA WMS LOGIC ---

        except Exception as e:
            logger.error(f"Order cancellation failed during transaction for {order_id}: {e}") # <-- ADDED
            return Response(
                {"error": f"Order cancellation failed during transaction: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 4. Transaction ke BAAD, Celery task ko trigger karein
        if payment_to_refund:
            try:
                # Humara updated refund task (jo partial refund nahi hai)
                process_razorpay_refund_task.delay(
                    payment_id=payment_to_refund.id,
                    is_partial_refund=False # Full refund
                )
                logger.info(f"Full Refund task for Payment ID {payment_to_refund.id} ko trigger kar diya gaya hai.") # <-- CHANGED
            except Exception as e:
                logger.critical(f"CRITICAL ERROR: Refund task trigger nahi ho paaya for order {order_id}: {e}") # <-- CHANGED
                pass

        # 5. User ko response dein
        order.refresh_from_db() 
        serializer = self.get_serializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

@method_decorator(csrf_exempt, name='dispatch')
class RazorpayWebhookView(APIView):
    """
    Razorpay Webhook Endpoint.
    Yeh Razorpay se server-to-server updates (jaise 'payment.captured')
    receive karta hai. Yeh client-side verification ka backup hai.
    """
    permission_classes = [AllowAny] # Koi bhi (Razorpay) isse call kar sakta hai

    def post(self, request, *args, **kwargs):
        
        # Step 1: Webhook signature ko verify karein
        raw_body = request.body
        webhook_signature = request.headers.get('X-Razorpay-Signature')
        
        if webhook_signature is None:
            return Response(
                {"error": "Signature header missing."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Secret ke saath signature verify karein
            client = razorpay.Client(
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            )
            client.utility.verify_webhook_signature(
                raw_body.decode('utf-8'), 
                webhook_signature, 
                settings.RAZORPAY_WEBHOOK_SECRET
            )
        except razorpay.errors.SignatureVerificationError:
            logger.warning("Webhook Signature Verification Failed") # <-- CHANGED
            return Response(
                {"error": "Invalid signature."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Webhook error (Header Verify): {e}") # <-- CHANGED
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Step 2: Signature valid hai, ab payload process karein
        try:
            payload = json.loads(raw_body)
            event = payload.get('event')

            if event == 'payment.captured':
                payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
                razorpay_order_id = payment_entity.get('order_id')
                razorpay_payment_id = payment_entity.get('id')

                if not razorpay_order_id or not razorpay_payment_id:
                    return Response({"error": "Payload missing data."}, status=status.HTTP_400_BAD_REQUEST)

                # Apne 'Payment' object ko dhoondein
                try:
                    payment = Payment.objects.get(razorpay_order_id=razorpay_order_id)
                    order = payment.order
                    
                    # Agar order pehle hi PENDING hai (yaani process nahi hua)
                    if order.status == Order.OrderStatus.PENDING:
                        logger.info(f"Webhook: Processing PENDING order {order.order_id}") # <-- CHANGED
                        
                        # Payment ID update karein
                        payment.transaction_id = razorpay_payment_id
                        payment.save()
                        
                        # Hamara common function call karein
                        success, result = process_successful_payment(order.order_id)
                        
                        if success:
                            logger.info(f"Webhook: Successfully processed order {order.order_id}") # <-- CHANGED
                        else:
                            logger.error(f"Webhook: Failed to process order {order.order_id}: {result}") # <-- CHANGED
                    
                    elif order.status == Order.OrderStatus.CONFIRMED:
                        logger.info(f"Webhook: Order {order.order_id} is already confirmed. Ignoring.") # <-- CHANGED
                        
                except Payment.DoesNotExist:
                    logger.warning(f"Webhook ERROR: Payment with RZP Order ID {razorpay_order_id} not found.") # <-- CHANGED
                    # Hum 404 nahi bhejenge, 200 hi bhejenge taaki Razorpay retry na kare
                    pass
            
            else:
                logger.info(f"Webhook: Received unhandled event '{event}'") # <-- CHANGED

            # Hamesha 200 OK return karein
            return Response(
                {"status": "ok"}, 
                status=status.HTTP_200_OK
            )
            
        except json.JSONDecodeError:
            logger.error("Webhook payload processing error: Invalid JSON") # <-- ADDED
            return Response({"error": "Invalid JSON payload."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Webhook payload processing error: {e}") # <-- CHANGED
            return Response({"error": "Internal server error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class RiderRatingView(generics.GenericAPIView):
    """
    API: POST /api/orders/<order_id>/rate-delivery/
    Customer ko order deliver hone ke baad rider ko rate karne deta hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = RiderRatingSerializer # Hamara naya serializer

    @transaction.atomic # Database consistency ke liye
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data
        
        order_id = self.kwargs.get('order_id')

        # 1. Order ko dhoondein aur check karein ki woh user ka hai
        try:
            order = Order.objects.get(order_id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        # 2. Status check karein (Sirf DELIVERED order hi rate ho sakte hain)
        if order.status != Order.OrderStatus.DELIVERED:
            return Response(
                {"error": "Aap sirf 'DELIVERED' orders ko hi rate kar sakte hain."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. Delivery object dhoondein
        try:
            # Hum order se delivery tak OneToOne related_name 'delivery' ka istemaal kar rahe hain
            delivery = order.delivery 
        except Delivery.DoesNotExist:
            # Aisa hona nahi chahiye agar order delivered hai, lekin safety check
            return Response({"error": "Delivery details not found for this order."}, status=status.HTTP_404_NOT_FOUND)

        # 4. Check karein ki pehle se rated toh nahi hai
        if delivery.rider_rating is not None:
            return Response(
                {"error": "Aap is delivery ko pehle hi rate kar chuke hain."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # 5. Rating ko Delivery object par save karein
        delivery.rider_rating = validated_data['rating']
        delivery.rider_rating_comment = validated_data.get('comment')
        delivery.save(update_fields=['rider_rating', 'rider_rating_comment'])

        # 6. Rider ki average rating update karein
        rider = delivery.rider
        if rider:
            # Rider ki sabhi *rated* deliveries ka average nikaalein
            new_avg = Delivery.objects.filter(
                rider=rider, 
                rider_rating__isnull=False # Sirf rated wali
            ).aggregate(
                avg_rating=Avg('rider_rating')
            )['avg_rating']
            
            if new_avg is not None:
                # RiderProfile par rating update karein
                rider.rating = Decimal(new_avg).quantize(Decimal('0.01'))
                rider.save(update_fields=['rating'])
        
        return Response(
            {"success": "Rider rated successfully."},
            status=status.HTTP_200_OK
        )



class ReorderView(generics.GenericAPIView):
    """
    API: POST /api/orders/<order_id>/reorder/
    Ek puraane order ko "re-order" karta hai.
    Yeh puraane order ke items ko user ke current cart mein add karta hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = CartSerializer # Response mein poora cart bhejenge

    def post(self, request, *args, **kwargs):
        order_id = self.kwargs.get('order_id')
        user = request.user

        try:
            # 1. Puraana order dhoondein aur check karein ki woh user ka hai
            original_order = Order.objects.get(
                order_id=order_id, 
                user=user
            )
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        # 2. User ka cart dhoondein (ya banayein)
        cart, _ = Cart.objects.get_or_create(user=user)
        
        # 3. Puraane order ke items lein
        original_items = original_order.items.all().select_related(
            'inventory_item__variant__product' # Performance ke liye
        )

        if not original_items.exists():
            return Response({"error": "Original order has no items."}, status=status.HTTP_400_BAD_REQUEST)

        # 4. Store check karein (puraane order wala store)
        order_store = original_order.store
        if not order_store:
            return Response({"error": "Cannot reorder from an unknown store."}, status=status.HTTP_400_BAD_REQUEST)

        items_added = []
        items_unavailable = []
        
        try:
            with transaction.atomic():
                # 5. User ke current cart ko khaali karein
                # Yeh ensure karta hai ki cart mein sirf naye items hon
                cart.items.all().delete()

                # 6. Har puraane item ko process karein
                for item in original_items:
                    item_name = f"{item.product_name} ({item.variant_name})"
                    
                    try:
                        # 7. Check karein ki woh inventory item abhi bhi maujood hai
                        current_inventory_item = StoreInventory.objects.get(
                            id=item.inventory_item_id,
                            store=order_store
                        )
                        
                        # 8. Stock check karein
                        if current_inventory_item.is_in_stock and current_inventory_item.stock_quantity >= item.quantity:
                            # Item available hai, cart mein add karein
                            CartItem.objects.create(
                                cart=cart,
                                inventory_item=current_inventory_item,
                                quantity=item.quantity
                            )
                            items_added.append(f"{item.quantity} x {item_name}")
                        else:
                            # Out of stock
                            items_unavailable.append(f"{item_name} (Out of Stock)")
                            
                    except StoreInventory.DoesNotExist:
                        # Item ab bikna band ho gaya hai
                        items_unavailable.append(f"{item_name} (No longer available)")

                # 7. Agar koi bhi item add nahi ho paaya, toh transaction rollback karein
                if not items_added:
                    raise Exception("Reorder failed: All items are unavailable.")

        except Exception as e:
            # Agar transaction fail hua (e.g., saare items unavailable)
            logger.warning(f"Reorder failed for user {user.username}, order {order_id}: {e}") # <-- ADDED
            return Response(
                {"error": str(e), "items_unavailable": items_unavailable},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 8. Success response: Naya cart data aur summary bhejein
        cart.refresh_from_db() # Cart ko update karein
        serializer = self.get_serializer(cart, context={'request': request})
        
        return Response({
            "message": "Cart has been updated with available items.",
            "items_added": items_added,
            "items_unavailable": items_unavailable,
            "cart": serializer.data
        }, status=status.HTTP_200_OK)