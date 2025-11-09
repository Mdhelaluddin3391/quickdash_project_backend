# File: dashboard/views.py (Cleaned Version)

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal
from django.db import transaction
from django.conf import settings

# Model Imports
from orders.models import Order, OrderItem, Payment
from inventory.models import StoreInventory
from wms.models import PickTask, WmsStock
from delivery.models import Delivery
from accounts.models import User

# Serializer Imports
from .serializers import (
    StaffDashboardSerializer, 
    ManagerOrderListSerializer, 
    CancelOrderItemSerializer,
    ManagerCustomerDetailSerializer
)
from orders.serializers import OrderDetailSerializer # Output ke liye

# Task Imports
from orders.tasks import process_razorpay_refund_task

# Permission Imports
from accounts.permissions import IsStoreStaff
# Humne "IsStoreManager" ko WMS se import kiya hai
from wms.permissions import IsStoreManager

# Helper Function
from delivery.utils import notify_nearby_riders


class StaffDashboardView(generics.GenericAPIView):
    """
    API: GET /api/dashboard/staff/
    Store Staff (Manager/Picker) ko unke store ka overview deta hai.
    """
    permission_classes = [IsAuthenticated, IsStoreStaff]
    serializer_class = StaffDashboardSerializer

    def get(self, request, *args, **kwargs):
        try:
            store = request.user.store_staff_profile.store
            if not store:
                return Response({"error": "Aap kisi store se assign nahi hain."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({"error": "Store staff profile nahi mila."}, status=status.HTTP_400_BAD_REQUEST)

        today = timezone.now().date()
        
        # Successful orders (failed/cancelled nahi)
        successful_orders_today = Order.objects.filter(
            store=store,
            created_at__date=today
        ).exclude(
            status__in=[Order.OrderStatus.FAILED, Order.OrderStatus.CANCELLED]
        )
        
        today_sales_agg = successful_orders_today.aggregate(
            total_sales=Sum('final_total')
        )
        today_sales = today_sales_agg['total_sales'] or Decimal('0.00')
        today_orders_count = successful_orders_today.count()

        # Active Orders (jinpar kaam baaki hai)
        active_orders = Order.objects.filter(store=store)
        preparing_orders_count = active_orders.filter(
            status=Order.OrderStatus.PREPARING
        ).count()
        ready_for_pickup_orders_count = active_orders.filter(
            status=Order.OrderStatus.READY_FOR_PICKUP
        ).count()

        # Pending Pick Tasks
        pending_pick_tasks = PickTask.objects.filter(
            order__store=store,
            status=PickTask.PickStatus.PENDING
        ).count()

        # Low stock items
        LOW_STOCK_THRESHOLD = 10
        low_stock_items = StoreInventory.objects.filter(
            store=store,
            is_available=True,
            stock_quantity__gt=0,
            stock_quantity__lt=LOW_STOCK_THRESHOLD
        ).select_related(
            'variant__product'
        ).order_by('stock_quantity')[:10]

        data = {
            'today_sales': today_sales,
            'today_orders_count': today_orders_count,
            'pending_pick_tasks': pending_pick_tasks,
            'preparing_orders_count': preparing_orders_count,
            'ready_for_pickup_orders_count': ready_for_pickup_orders_count,
            'low_stock_items': low_stock_items
        }

        serializer = self.get_serializer(data, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    

class ManagerOrderListView(generics.ListAPIView):
    """
    API: GET /api/dashboard/staff/orders/
    Manager ko store ke sabhi orders ko filter/search karne deta hai.
    """
    # Yeh feature manager ke liye hona chahiye
    permission_classes = [IsAuthenticated, IsStoreManager]
    serializer_class = ManagerOrderListSerializer

    def get_queryset(self):
        store = self.request.user.store_staff_profile.store
        if not store:
            return Order.objects.none()
        
        queryset = Order.objects.filter(store=store).select_related('user').order_by('-created_at')

        status = self.request.query_params.get('status')
        order_id = self.request.query_params.get('order_id')
        phone = self.request.query_params.get('phone')

        if status:
            queryset = queryset.filter(status=status)
        if order_id:
            queryset = queryset.filter(order_id__icontains=order_id)
        if phone:
            queryset = queryset.filter(user__phone_number__icontains=phone)
        
        return queryset
    

class CancelOrderItemView(generics.GenericAPIView):
    """
    API: POST /api/dashboard/staff/order-item/cancel/
    Manager ko ek order item ko FC (Fulfilment Cancel) karne deta hai.
    """
    # Yeh ek powerful action hai, sirf Manager ke liye
    permission_classes = [IsAuthenticated, IsStoreManager]
    serializer_class = CancelOrderItemSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order_item_id = serializer.validated_data['order_item_id']
        quantity_to_cancel = serializer.validated_data['quantity_to_cancel']
        
        staff_store = request.user.store_staff_profile.store

        try:
            with transaction.atomic():
                order_item = OrderItem.objects.select_for_update().get(id=order_item_id)
                order = order_item.order
                
                # Validations
                if order.store != staff_store:
                    raise Exception("Aap yeh order item cancel nahi kar sakte (galat store).")
                if order.status not in [Order.OrderStatus.CONFIRMED, Order.OrderStatus.PREPARING]:
                    raise Exception(f"Order ko '{order.status}' status mein cancel nahi kiya ja sakta.")
                if quantity_to_cancel > order_item.quantity:
                    raise Exception(f"Aap {quantity_to_cancel} cancel nahi kar sakte. Item ki quantity sirf {order_item.quantity} hai.")

                # WMS Pick Tasks ko Cancel/Update karein
                pending_tasks = PickTask.objects.filter(
                    order=order,
                    variant=order_item.inventory_item.variant,
                    status=PickTask.PickStatus.PENDING
                ).order_by('-quantity_to_pick') # Bade task pehle
                
                wms_qty_to_cancel = quantity_to_cancel
                tasks_to_update = []
                
                for task in pending_tasks:
                    if wms_qty_to_cancel <= 0: break
                    if task.quantity_to_pick <= wms_qty_to_cancel:
                        task.status = PickTask.PickStatus.CANCELLED
                        tasks_to_update.append(task)
                        wms_qty_to_cancel -= task.quantity_to_pick
                    else:
                        task.quantity_to_pick -= wms_qty_to_cancel
                        tasks_to_update.append(task)
                        wms_qty_to_cancel = 0
                
                PickTask.objects.bulk_update(tasks_to_update, ['status', 'quantity_to_pick'])
                
                # BUG FIX: Agar quantity cancel karne ke liye PENDING task nahi mile
                # (yaani task pehle hi COMPLETE ho chuka hai), toh error dein.
                if wms_qty_to_cancel > 0:
                    # Check karein ki task complete toh nahi ho gaya
                    completed_tasks_exist = PickTask.objects.filter(
                        order=order,
                        variant=order_item.inventory_item.variant,
                        status=PickTask.PickStatus.COMPLETED
                    ).exists()
                    if completed_tasks_exist:
                         raise Exception(f"FC Failed: Item '{order_item.variant_name}' pehle hi pick ho chuka hai.")
                    else:
                         print(f"WARNING: FC ke liye PENDING pick tasks nahi mile. {wms_qty_to_cancel} quantity cancel nahi ho paayi.")

                # OrderItem aur Order ko Recalculate karein
                price_per_unit = order_item.price_at_order
                total_item_price_to_cancel = price_per_unit * quantity_to_cancel
                
                order_item.quantity -= quantity_to_cancel
                if order_item.quantity == 0:
                    order_item.delete()
                else:
                    order_item.save()
                
                original_final_total = order.final_total
                new_subtotal = order.item_subtotal - total_item_price_to_cancel
                
                new_discount = Decimal('0.00')
                if order.coupon:
                    new_discount = order.coupon.calculate_discount(new_subtotal)
                    if not order.coupon.is_valid(new_subtotal)[0]:
                        new_discount = Decimal('0.00')
                
                tax_rate = getattr(settings, 'TAX_RATE', Decimal('0.05'))
                new_taxable_amount = new_subtotal - new_discount
                new_taxes = (new_taxable_amount * tax_rate).quantize(Decimal('0.01'))
                
                new_final_total = (
                    new_taxable_amount + new_taxes + 
                    order.delivery_fee + order.rider_tip
                ).quantize(Decimal('0.01'))
                
                total_to_refund = original_final_total - new_final_total
                
                order.item_subtotal = new_subtotal
                order.discount_amount = new_discount
                order.taxes_amount = new_taxes
                order.final_total = new_final_total
                order.save()

            # Transaction ke BAAD, Refund Trigger karein
            if total_to_refund > 0:
                payment = order.payments.filter(
                    status=Order.PaymentStatus.SUCCESSFUL,
                    payment_method='RAZORPAY'
                ).first()
                
                if payment:
                    refund_paise = int(total_to_refund * 100)
                    process_razorpay_refund_task.delay(
                        payment_id=payment.id, 
                        amount_to_refund_paise=refund_paise, 
                        is_partial_refund=True
                    )
                    print(f"Partial refund task (₹{total_to_refund}) for order {order.order_id} triggered.")

            serializer = OrderDetailSerializer(order, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        except OrderItem.DoesNotExist:
            return Response({"error": "Order item not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"FC failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        

class ManualPackView(generics.GenericAPIView):
    """
    API: POST /api/dashboard/staff/order/<order_id>/mark-packed/
    Manager ko ek order ko "Manually Packed" mark karne deta hai.
    """
    # Yeh ek powerful action hai, sirf Manager ke liye
    permission_classes = [IsAuthenticated, IsStoreManager]
    
    def post(self, request, *args, **kwargs):
        order_id = self.kwargs.get('order_id')
        staff_store = request.user.store_staff_profile.store

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(order_id=order_id)
                delivery = Delivery.objects.select_for_update().get(order=order)

                if order.store != staff_store:
                    raise Exception("Aap yeh order pack nahi kar sakte (galat store).")
                if order.status not in [Order.OrderStatus.CONFIRMED, Order.OrderStatus.PREPARING]:
                    raise Exception(f"Order ko '{order.status}' status mein pack nahi kiya ja sakta.")

                pending_tasks = PickTask.objects.filter(
                    order=order, 
                    status=PickTask.PickStatus.PENDING
                ).select_for_update()

                if not pending_tasks.exists():
                    print(f"Info: Manual pack for {order_id} ke liye koi PENDING task nahi mila. Sirf status change hoga.")
                
                tasks_to_complete = []
                
                for task in pending_tasks:
                    try:
                        stock_item = WmsStock.objects.select_for_update().get(
                            inventory_summary__variant=task.variant,
                            location=task.location
                        )
                        if stock_item.quantity < task.quantity_to_pick:
                            raise Exception(f"Stock Kam Hai! Location {task.location.code} par {task.variant.sku} ke liye {task.quantity_to_pick} chahiye, par {stock_item.quantity} hi hain.")

                        stock_item.quantity -= task.quantity_to_pick
                        stock_item.save()
                        
                        task.status = PickTask.PickStatus.COMPLETED
                        task.completed_at = timezone.now()
                        tasks_to_complete.append(task)
                        
                    except WmsStock.DoesNotExist:
                        raise Exception(f"Stock Item (WMS) {task.variant.sku} location {task.location.code} par nahi mila.")
                
                if tasks_to_complete:
                    PickTask.objects.bulk_update(tasks_to_complete, ['status', 'completed_at'])
                    print(f"Manually packed {len(tasks_to_complete)} pick tasks for order {order_id}")

                order.status = Order.OrderStatus.READY_FOR_PICKUP
                order.save()
                
                delivery.status = Delivery.DeliveryStatus.PENDING_ACCEPTANCE
                delivery.save()
            
            # Transaction ke BAAD, Riders ko Notify karein
            notify_nearby_riders(delivery, context={'request': request})
            
            serializer = OrderDetailSerializer(order, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)
        except Delivery.DoesNotExist:
            return Response({"error": "Delivery object for this order not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"Manual Pack failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        


class CustomerLookupView(generics.GenericAPIView):
    """
    API: GET /api/dashboard/staff/customer-lookup/?phone=+91...
    Manager ko customer details (profile, addresses) phone number se search karne deta hai.
    """
    # Yeh feature manager ke liye hona chahiye
    permission_classes = [IsAuthenticated, IsStoreManager]
    serializer_class = ManagerCustomerDetailSerializer

    def get(self, request, *args, **kwargs):
        phone_number = self.request.query_params.get('phone')

        if not phone_number:
            return Response(
                {"error": "Query parameter 'phone' zaroori hai (e.g., ?phone=+91...)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.prefetch_related(
                'customer_profile',
                'addresses'
            ).get(
                phone_number=phone_number,
                customer_profile__isnull=False
            )
        except User.DoesNotExist:
            return Response(
                {"error": "Is phone number se koi customer nahi mila."},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(user, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)