from django.shortcuts import render

# Create your views here.
# wms/views.py
from rest_framework import generics, status
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction

from .models import PickTask, WmsStock
from .serializers import (
    WmsStockReceiveSerializer, 
    PickTaskSerializer
)
from .permissions import IsStoreManager, IsStorePicker
# wms/views.py (TOP PAR ADD KAREIN)

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance

from delivery.models import RiderProfile
from delivery.serializers import RiderDeliverySerializer

# Workflow A: Stock Receive Karna
# (Design Doc: POST /api/wms/receive-stock/)

class ReceiveStockView(generics.GenericAPIView):
    """
    API: POST /api/wms/receive-stock/
    Store Manager ko granular stock (WmsStock) add karne deta hai.
    """
    permission_classes = [IsStoreManager]
    serializer_class = WmsStockReceiveSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Serializer ka .create() method WmsStock entry banayega/update karega
        # aur signal StoreInventory ko sync kar dega.
        wms_stock_item = serializer.save() 

        return Response(
            {
                "success": "Stock updated successfully.",
                "location": wms_stock_item.location.code,
                "sku": wms_stock_item.inventory_summary.variant.sku,
                "new_location_quantity": wms_stock_item.quantity,
                "total_product_stock": wms_stock_item.inventory_summary.stock_quantity
            },
            status=status.HTTP_201_CREATED
        )

# Workflow B: Picker ke Tasks
# (Design Doc: GET /api/wms/my-pick-tasks/)

class PickerTaskListView(generics.ListAPIView):
    """
    API: GET /api/wms/my-pick-tasks/
    Picker ko usse assign kiye gaye 'PENDING' tasks dikhata hai.
    """
    permission_classes = [IsStorePicker]
    serializer_class = PickTaskSerializer

    def get_queryset(self):
        # Sirf woh tasks jo is user ko assigned hain aur PENDING hain
        return PickTask.objects.filter(
            assigned_to=self.request.user,
            status=PickTask.PickStatus.PENDING
        ).select_related(
            'variant__product', 
            'location', 
            'order'
        ).order_by('created_at') # Sabse purana task pehle

# wms/views.py (Sirf is class ko replace karein)

# ... (ReceiveStockView aur PickerTaskListView waise hi rahenge) ...

class PickTaskCompleteView(generics.GenericAPIView):
    """
    API: POST /api/wms/pick-tasks/<int:pk>/complete/
    Picker ko ek task 'COMPLETED' mark karne deta hai.
    --- AB YEH RIDERS KO NOTIFY BHI KARTA HAI ---
    """
    permission_classes = [IsStorePicker]
    serializer_class = PickTaskSerializer # Output dikhane ke liye

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        try:
            task = PickTask.objects.select_related('order__store__location').get(
                id=pk,
                assigned_to=request.user,
                status=PickTask.PickStatus.PENDING
            )
        except PickTask.DoesNotExist:
            return Response(
                {"error": "Task not found or already completed."}, 
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            with transaction.atomic():
                # 1. WmsStock ko lock karein aur quantity kam karein
                stock_item = WmsStock.objects.select_for_update().get(
                    inventory_summary__variant=task.variant,
                    inventory_summary__store=request.user.store_staff_profile.store,
                    location=task.location
                )

                if stock_item.quantity < task.quantity_to_pick:
                    raise Exception(f"Not enough stock at {task.location.code}. Expected {task.quantity_to_pick}, found {stock_item.quantity}.")

                stock_item.quantity -= task.quantity_to_pick
                stock_item.save() 

                # 2. Task ko 'COMPLETED' mark karein
                task.status = PickTask.PickStatus.COMPLETED
                task.completed_at = timezone.now()
                task.save()

                # 3. Check karein ki order ke sabhi tasks complete ho gaye
                order = task.order
                pending_tasks_count = order.pick_tasks.filter(
                    status=PickTask.PickStatus.PENDING
                ).count()

                delivery_object_for_notification = None # Notification ke liye variable

                if pending_tasks_count == 0:
                    # SABHI TASKS COMPLETE!
                    from orders.models import Order
                    from delivery.models import Delivery

                    order.status = Order.OrderStatus.READY_FOR_PICKUP
                    order.save(update_fields=['status'])

                    delivery = order.delivery
                    delivery.status = Delivery.DeliveryStatus.PENDING_ACCEPTANCE
                    delivery.save(update_fields=['status'])

                    delivery_object_for_notification = delivery # Notification ke liye set karein

                    print(f"Order {order.order_id} is now READY_FOR_PICKUP.")

            # --- TRANSACTION KE BAAD (TAAKI DB LOCK NA RAHE) ---

            # 4. (NAYA NOTIFICATION LOGIC)
            # Agar order ready hua hai, toh riders ko notify karein
            if delivery_object_for_notification:
                try:
                    store_location = order.store.location
                    if not store_location:
                        raise Exception("Store ki location set nahi hai.")

                    nearby_available_riders = RiderProfile.objects.filter(
                        is_online=True,
                        on_delivery=False,
                        current_location__isnull=False,
                        current_location__distance_lte=(
                            store_location, 
                            D(km=settings.RIDER_SEARCH_RADIUS_KM)
                        )
                    ).annotate(
                        distance_to_store=Distance('current_location', store_location)
                    ).order_by('distance_to_store')[:10]

                    if not nearby_available_riders.exists():
                        print(f"Order {order.order_id} (WMS) READY, lekin koi nearby rider available nahi hai.")
                    else:
                        channel_layer = get_channel_layer()
                        # Hum request object pass kar rahe hain taaki media URLs sahi bane
                        delivery_data = RiderDeliverySerializer(
                            delivery_object_for_notification, 
                            context={'request': request}
                        ).data

                        for rider in nearby_available_riders:
                            group_name = f"rider_{rider.id}"
                            async_to_sync(channel_layer.group_send)(
                                group_name,
                                {
                                    "type": "new.delivery.notification", 
                                    "delivery": delivery_data
                                }
                            )

                        print(f"Order {order.order_id} (WMS) READY. Notified {len(nearby_available_riders)} nearby riders.")

                except Exception as e:
                    # Agar notification fail bhi ho, toh picker ko error na dikhe
                    print(f"CRITICAL: Order ready, but failed to send rider notification: {e}")

            # --- END NAYA NOTIFICATION LOGIC ---

            serializer = self.get_serializer(task)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except WmsStock.DoesNotExist:
             return Response(
                {"error": "Stock item not found at the specified location."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            # Agar transaction fail hua, toh error dein
            return Response(
                {"error": f"Failed to complete task: {str(e)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )