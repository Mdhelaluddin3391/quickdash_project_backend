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

# Task Imports
from .tasks import process_razorpay_refund_task

# Model Imports
from .models import Order, OrderItem, Payment, Address, Coupon
from cart.models import Cart
from inventory.models import StoreInventory
from delivery.models import Delivery 

# Serializer Imports
from delivery.serializers import RiderDeliverySerializer 
from .serializers import (
    CheckoutSerializer, 
    OrderDetailSerializer, 
    OrderHistorySerializer,
    PaymentVerificationSerializer,
    RiderRatingSerializer
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
    (BUG FIX APPLIED: Refund logic ko Celery task mein move kar diya gaya hai)
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = OrderDetailSerializer

    def post(self, request, *args, **kwargs):
        order_id = self.kwargs.get('order_id')
        try:
            order = Order.objects.get(
                order_id=order_id,
                user=request.user
            )
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        # 1. Check karein ki order cancel ho sakta hai ya nahi
        if order.status not in [Order.OrderStatus.PENDING, Order.OrderStatus.CONFIRMED]:
            return Response(
                {"error": f"Order in status '{order.status}' cannot be cancelled."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 2. Time window check karein
        if order.status == Order.OrderStatus.CONFIRMED:
            confirmation_time = order.updated_at 
            # settings.ORDER_CANCELLATION_WINDOW ko settings.py mein define karein (e.g., 300 seconds)
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
                        # Refund ke liye mark karein
                        payment_to_refund = payment
                        # Naya status set karein
                        payment.status = Order.PaymentStatus.REFUND_INITIATED
                        payment.save(update_fields=['status'])
                        
                        order_lock.payment_status = Order.PaymentStatus.REFUND_INITIATED
                    else:
                        # Yeh COD ya free order tha, bas REFUNDED mark karein
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
                    pass # Koi baat nahi agar delivery create nahi hui thi

                # Stock revert karein (sirf agar order 'CONFIRMED' tha)
                if original_status == Order.OrderStatus.CONFIRMED:
                    order_items = order_lock.items.all()
                    inventory_items_to_update = []
                    
                    for item in order_items:
                        if item.inventory_item:
                            try:
                                inv_item = StoreInventory.objects.select_for_update().get(id=item.inventory_item.id)
                                inv_item.stock_quantity = F('stock_quantity') + item.quantity
                                inventory_items_to_update.append(inv_item)
                            except StoreInventory.DoesNotExist:
                                print(f"Warning: Stock revert karte waqt Item {item.inventory_item.id} nahi mila.")
                    
                    if inventory_items_to_update:
                        StoreInventory.objects.bulk_update(inventory_items_to_update, ['stock_quantity'])
                        print(f"Stock reverted for {len(inventory_items_to_update)} items.")

        except Exception as e:
            # Agar transaction fail hota hai (e.g., delivery picked up ho gayi thi)
            return Response(
                {"error": f"Order cancellation failed during transaction: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # 4. Transaction ke BAAD, Celery task ko trigger karein
        if payment_to_refund:
            try:
                # payment_to_refund.id (Payment object ki ID) bhej rahe hain
                process_razorpay_refund_task.delay(payment_to_refund.id)
                print(f"Refund task for Payment ID {payment_to_refund.id} ko trigger kar diya gaya hai.")
            except Exception as e:
                # Agar Celery down hai, toh admin ko manual refund ke liye alert karein
                print(f"CRITICAL ERROR: Refund task trigger nahi ho paaya: {e}")
                # Hum user ko error nahi dikhayenge, kyunki order cancel ho chuka hai
                # Yahaan par logging (e.g., Sentry) zaroori hai
                pass

        # 5. User ko response dein
        # Order object ko refresh karein taaki naya status dikhe
        order.refresh_from_db() 
        serializer = self.get_serializer(order, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# ... (Aapke baaqi views jaise RazorpayWebhookView, RiderRatingView, etc. yahaan rahenge) ...


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
            print("Webhook Signature Verification Failed")
            return Response(
                {"error": "Invalid signature."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            print(f"Webhook error: {e}")
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
                        print(f"Webhook: Processing PENDING order {order.order_id}")
                        
                        # Payment ID update karein
                        payment.transaction_id = razorpay_payment_id
                        payment.save()
                        
                        # Hamara common function call karein
                        success, result = process_successful_payment(order.order_id)
                        
                        if success:
                            print(f"Webhook: Successfully processed order {order.order_id}")
                        else:
                            print(f"Webhook: Failed to process order {order.order_id}: {result}")
                    
                    elif order.status == Order.OrderStatus.CONFIRMED:
                        print(f"Webhook: Order {order.order_id} is already confirmed. Ignoring.")
                        
                except Payment.DoesNotExist:
                    print(f"Webhook ERROR: Payment with RZP Order ID {razorpay_order_id} not found.")
                    # Hum 404 nahi bhejenge, 200 hi bhejenge taaki Razorpay retry na kare
                    pass
            
            else:
                print(f"Webhook: Received unhandled event '{event}'")

            # Hamesha 200 OK return karein
            return Response(
                {"status": "ok"}, 
                status=status.HTTP_200_OK
            )
            
        except json.JSONDecodeError:
            return Response({"error": "Invalid JSON payload."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print(f"Webhook payload processing error: {e}")
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