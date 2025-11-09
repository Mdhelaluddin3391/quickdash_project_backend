from django.shortcuts import render
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

# Naya Helper Function import
from delivery.utils import notify_nearby_riders


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


class PickerTaskListView(generics.ListAPIView):
    """
    API: GET /api/wms/my-pick-tasks/
    Picker ko usse assign kiye gaye 'PENDING' tasks dikhata hai.
    """
    permission_classes = [IsStorePicker]
    serializer_class = PickTaskSerializer

    def get_queryset(self):
        return PickTask.objects.filter(
            assigned_to=self.request.user,
            status=PickTask.PickStatus.PENDING
        ).select_related(
            'variant__product', 
            'location', 
            'order'
        ).order_by('created_at')


class PickTaskCompleteView(generics.GenericAPIView):
    """
    API: POST /api/wms/pick-tasks/<int:pk>/complete/
    Picker ko ek task 'COMPLETED' mark karne deta hai.
    --- (UPDATED: Ab helper function use karta hai) ---
    """
    permission_classes = [IsStorePicker]
    serializer_class = PickTaskSerializer

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
                stock_item = WmsStock.objects.select_for_update().get(
                    inventory_summary__variant=task.variant,
                    inventory_summary__store=request.user.store_staff_profile.store,
                    location=task.location
                )

                if stock_item.quantity < task.quantity_to_pick:
                    raise Exception(f"Not enough stock at {task.location.code}. Expected {task.quantity_to_pick}, found {stock_item.quantity}.")

                stock_item.quantity -= task.quantity_to_pick
                stock_item.save() 

                task.status = PickTask.PickStatus.COMPLETED
                task.completed_at = timezone.now()
                task.save()

                order = task.order
                pending_tasks_count = order.pick_tasks.filter(
                    status=PickTask.PickStatus.PENDING
                ).count()

                delivery_object_for_notification = None 

                if pending_tasks_count == 0:
                    from orders.models import Order
                    from delivery.models import Delivery

                    order.status = Order.OrderStatus.READY_FOR_PICKUP
                    order.save(update_fields=['status'])

                    delivery = order.delivery
                    delivery.status = Delivery.DeliveryStatus.PENDING_ACCEPTANCE
                    delivery.save(update_fields=['status'])

                    delivery_object_for_notification = delivery 
                    print(f"Order {order.order_id} is now READY_FOR_PICKUP.")

            # Transaction ke BAAD
            if delivery_object_for_notification:
                try:
                    # --- UPDATED CALL ---
                    notify_nearby_riders(
                        delivery_object_for_notification, 
                        context={'request': request}
                    )
                except Exception as e:
                    pass # Helper function ab errors ko internally log karta hai

            serializer = self.get_serializer(task)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except WmsStock.DoesNotExist:
             return Response(
                {"error": "Stock item not found at the specified location."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to complete task: {str(e)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )