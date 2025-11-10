# File: dashboard/views.py (Cleaned Version)

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from wms.models import PickTask, WmsStock # PickTask import karein
from wms.serializers import PickTaskSerializer # PickTaskSerializer import karein
from accounts.permissions import IsStoreStaff
from wms.permissions import IsStoreManager
# Model Imports
from orders.models import Order, OrderItem, Payment
from inventory.models import StoreInventory
from wms.models import PickTask, WmsStock
from delivery.models import Delivery
from accounts.models import User
from datetime import timedelta
# Serializer Imports
from .serializers import (
    StaffDashboardSerializer, 
    ManagerOrderListSerializer, 
    CancelOrderItemSerializer,
    ManagerCustomerDetailSerializer,
    AnalyticsDashboardSerializer
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
    

class IssuePickTaskListView(generics.ListAPIView):
    """
    API: GET /api/dashboard/staff/issue-tasks/
    Manager ko woh sabhi pick tasks dikhata hai jinpar picker
    ne 'ISSUE' report kiya hai (e.g., "item nahi mila").
    """
    permission_classes = [IsAuthenticated, IsStoreManager]
    serializer_class = PickTaskSerializer # Hum WMS serializer ko reuse karenge

    def get_queryset(self):
        # Staff ke store ko fetch karein
        store = self.request.user.store_staff_profile.store
        if not store:
            return PickTask.objects.none()
        
        # Sirf uss store ke 'ISSUE' status waale tasks dhoondein
        return PickTask.objects.filter(
            order__store=store,
            status=PickTask.PickStatus.ISSUE
        ).select_related(
            'variant__product', 
            'location', 
            'order'
        ).order_by('updated_at') # Jo sabse naya issue hai, woh pehle
    


class ResolveIssueTaskRetryView(generics.GenericAPIView):
    """
    API: POST /api/dashboard/staff/issue-task/<pk>/retry/
    Ek issue task ko 'PENDING' state mein reset karta hai (bina assigned picker ke).
    """
    permission_classes = [IsAuthenticated, IsStoreManager]

    def post(self, request, *args, **kwargs):
        store = request.user.store_staff_profile.store
        pk = self.kwargs.get('pk')
        
        try:
            # Task ko dhoondein aur lock karein
            task = PickTask.objects.select_for_update().get(
                id=pk, 
                order__store=store, 
                status=PickTask.PickStatus.ISSUE
            )
        except PickTask.DoesNotExist:
            return Response({"error": "Issue task not found or already resolved."}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            # Task ko reset karein
            task.status = PickTask.PickStatus.PENDING
            task.assigned_to = None # Kisi ko bhi assign nahi hai (ab 'Request New Task' se pull hoga)
            
            # Manager ka note add karein
            original_notes = task.picker_notes or "Issue reported"
            task.picker_notes = f"[Issue Resolved by {request.user.username}: Task Retried] {original_notes}"
            
            task.save()

        return Response(
            {"success": "Task has been reset and re-queued for picking."}, 
            status=status.HTTP_200_OK
        )


class ResolveIssueTaskCancelView(generics.GenericAPIView):
    """
    API: POST /api/dashboard/staff/issue-task/<pk>/cancel/
    Ek issue task ko 'CANCELLED' mark karta hai aur item ko order se
    (Fulfilment Cancel) remove karta hai.
    """
    permission_classes = [IsAuthenticated, IsStoreManager]

    def post(self, request, *args, **kwargs):
        store = request.user.store_staff_profile.store
        pk = self.kwargs.get('pk')
        
        try:
            with transaction.atomic():
                # 1. Task ko dhoondein
                task = PickTask.objects.select_for_update().get(
                    id=pk, 
                    order__store=store, 
                    status=PickTask.PickStatus.ISSUE
                )
                
                # 2. Corresponding OrderItem dhoondein
                # (Maan rahe hain ki ek order mein ek variant ek hi baar hota hai)
                order_item = OrderItem.objects.select_for_update().filter(
                    order=task.order, 
                    inventory_item__variant=task.variant
                ).first()

                if not order_item:
                    raise Exception("Corresponding OrderItem not found.")

                quantity_to_cancel = task.quantity_to_pick

                if quantity_to_cancel > order_item.quantity:
                    raise Exception(f"Cannot cancel {quantity_to_cancel}. Item quantity is only {order_item.quantity}.")

                # 3. OrderItem aur Order ko Recalculate karein
                # Yeh logic 'CancelOrderItemView' se liya gaya hai
                
                price_per_unit = order_item.price_at_order
                total_item_price_to_cancel = price_per_unit * quantity_to_cancel
                
                order_item.quantity -= quantity_to_cancel
                if order_item.quantity <= 0:
                    order_item.delete() # Item ko poora delete karein
                else:
                    order_item.save() # Sirf quantity kam karein

                # 4. Task ko 'CANCELLED' mark karein
                task.status = PickTask.PickStatus.CANCELLED
                original_notes = task.picker_notes or "Issue reported"
                task.picker_notes = f"[Issue Resolved by {request.user.username}: Item Cancelled] {original_notes}"
                task.save()

                # 5. Order Total ko Recalculate karein
                order = task.order
                original_final_total = order.final_total
                
                # Naya Subtotal
                new_subtotal = order.item_subtotal - total_item_price_to_cancel
                
                # Naya Discount (agar coupon tha)
                new_discount = Decimal('0.00')
                if order.coupon:
                    # Check karein ki coupon abhi bhi valid hai (kam total par)
                    if order.coupon.is_valid(new_subtotal)[0]:
                        new_discount = order.coupon.calculate_discount(new_subtotal)
                    # Agar valid nahi hai, toh discount 0 ho jayega
                
                # Naya Tax
                tax_rate = getattr(settings, 'TAX_RATE', Decimal('0.05'))
                new_taxable_amount = new_subtotal - new_discount
                new_taxes = (new_taxable_amount * tax_rate).quantize(Decimal('0.01'))
                
                # Naya Final Total
                new_final_total = (
                    new_taxable_amount + new_taxes + 
                    order.delivery_fee + order.rider_tip
                ).quantize(Decimal('0.01'))
                
                total_to_refund = original_final_total - new_final_total
                
                # Order par save karein
                order.item_subtotal = new_subtotal
                order.discount_amount = new_discount
                order.taxes_amount = new_taxes
                order.final_total = new_final_total
                order.save()

            # 6. Transaction ke BAAD, Refund Trigger karein
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
                    print(f"Partial refund task (₹{total_to_refund}) for order {order.order_id} triggered from IssueResolve.")

            # Poora updated order response mein bhejein
            serializer = OrderDetailSerializer(order, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        except PickTask.DoesNotExist:
            return Response({"error": "Issue task not found or already resolved."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": f"Failed to cancel item: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        


def get_date_range(period_param):
    """
    Ek helper function jo 'today', 'last_week' jaise string
    ko start_date aur end_date mein badalta hai.
    """
    now = timezone.now()
    today = now.date()
    start_date = None
    end_date = today + timedelta(days=1) # End date hamesha agle din ki subah tak

    if period_param == 'today':
        start_date = today
    elif period_param == 'last_week':
        start_date = today - timedelta(days=7)
    elif period_param == 'last_month':
        start_date = today - timedelta(days=30)
    elif period_param == 'last_3_months':
        start_date = today - timedelta(days=90)
    elif period_param == 'last_6_months':
        start_date = today - timedelta(days=180)
    elif period_param == 'last_year':
        start_date = today - timedelta(days=365)
    elif period_param == 'overall':
        start_date = None # Koi start date nahi
    else:
        # Default (agar galat param ho)
        start_date = today - timedelta(days=30)

    # Agar start_date hai, toh filter karein
    if start_date:
        return Q(created_at__gte=start_date, created_at__lt=end_date)
    else:
        # 'overall' ke liye
        return Q()


class AnalyticsDashboardView(generics.GenericAPIView):
    """
    API: GET /api/dashboard/staff/analytics/?period=last_month
    Manager ke liye poora analytics data.
    
    Query Params:
    - 'period': today, last_week, last_month (default), last_3_months, 
                last_6_months, last_year, overall
    """
    permission_classes = [IsAuthenticated, IsStoreManager]
    serializer_class = AnalyticsDashboardSerializer

    def get(self, request, *args, **kwargs):
        store = request.user.store_staff_profile.store
        period = request.query_params.get('period', 'last_month')
        
        # 1. Date range filter banayein
        date_filter = get_date_range(period)
        
        # 2. Sirf delivered orders ka base queryset banayein
        # Hum 'final_total' par analysis kar rahe hain
        base_orders_qs = Order.objects.filter(
            store=store,
            status=Order.OrderStatus.DELIVERED,
            **date_filter
        )
        
        # --- Query 1: Overview Stats (AOV, Total Revenue) ---
        overview_stats = base_orders_qs.aggregate(
            total_revenue=Sum('final_total'),
            total_orders=Count('id')
        )
        total_revenue = overview_stats.get('total_revenue') or Decimal('0.00')
        total_orders = overview_stats.get('total_orders') or 0
        average_order_value = (total_revenue / total_orders) if total_orders > 0 else Decimal('0.00')

        # --- Query 2: Top Selling Products ---
        # Iske liye humein OrderItems par query karni hogi
        top_products = OrderItem.objects.filter(
            order__in=base_orders_qs # Sirf delivered orders ke items
        ).values(
            'product_name', 'variant_name' # Group by
        ).annotate(
            total_quantity_sold=Sum('quantity'),
            total_revenue=Sum(F('quantity') * F('price_at_order'))
        ).order_by('-total_quantity_sold')[:10] # Top 10 by quantity

        # --- Query 3: Top Pincodes ---
        top_pincodes = base_orders_qs.filter(
            delivery_address__pincode__isnull=False
        ).values(
            'delivery_address__pincode' # Group by pincode
        ).annotate(
            order_count=Count('id')
        ).order_by('-order_count')[:10] # Top 10 by order count
        
        # Pincode ko rename karein (serializer ke liye)
        top_pincodes = [
            {'pincode': item['delivery_address__pincode'], 'order_count': item['order_count']}
            for item in top_pincodes
        ]

        # --- Query 4: Top Customers ---
        top_customers = User.objects.filter(
            orders__in=base_orders_qs # Jin users ke order delivered list mein hain
        ).annotate(
            order_count=Count('orders', filter=Q(orders__in=base_orders_qs)),
            total_spent=Sum('orders__final_total', filter=Q(orders__in=base_orders_qs))
        ).order_by('-total_spent')[:10] # Top 10 by total spending

        # --- Query 5: Rider Performance ---
        # Iske liye humein Delivery model par query karni hogi
        rider_performance = Delivery.objects.filter(
            order__in=base_orders_qs, # Sirf delivered orders
            rider__isnull=False,
            accepted_at__isnull=False,
            picked_up_at__isnull=False,
            delivered_at__isnull=False
        ).values(
            'rider__user__username' # Group by rider
        ).annotate(
            total_deliveries=Count('id'),
            # Avg(Picked up - At Store) -> Delivery time
            avg_delivery_duration=Avg(F('delivered_at') - F('picked_up_at')),
            # Avg(At Store - Accepted) -> Pickup time
            avg_pickup_duration=Avg(F('at_store_at') - F('accepted_at'))
        ).order_by('total_deliveries')
        
        # Serializer ke liye data ko format karein
        formatted_rider_performance = []
        for item in rider_performance:
            formatted_rider_performance.append({
                'rider_name': item['rider__user__username'],
                'total_deliveries': item['total_deliveries'],
                # DurationField ko seconds (float) mein convert karein
                'avg_pickup_time_seconds': item['avg_pickup_duration'].total_seconds() if item['avg_pickup_duration'] else None,
                'avg_delivery_time_seconds': item['avg_delivery_duration'].total_seconds() if item['avg_delivery_duration'] else None,
            })

        # --- Final Data Assembly ---
        data = {
            'total_revenue': total_revenue,
            'total_orders': total_orders,
            'average_order_value': average_order_value,
            'top_products': top_products,
            'top_pincodes': top_pincodes,
            'top_customers': top_customers,
            'rider_performance': formatted_rider_performance
        }

        serializer = self.get_serializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)