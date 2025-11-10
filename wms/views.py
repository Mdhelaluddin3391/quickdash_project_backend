import logging # <-- ADD
from django.shortcuts import render
from rest_framework import generics, status
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction

from .models import PickTask, WmsStock
from .serializers import (
    WmsStockReceiveSerializer, 
    PickTaskSerializer,
    PickTaskReportIssueSerializer
)
from .permissions import IsStoreManager, IsStorePicker

# Naya Helper Function import
# from delivery.utils import notify_nearby_riders # <-- REMOVED (Guarded below)

# Setup logger
logger = logging.getLogger(__name__) # <-- ADD


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
        # --- GUARDED IMPORTS ---
        from delivery.utils import notify_nearby_riders
        from orders.models import Order
        from delivery.models import Delivery
        # --- END GUARDED IMPORTS ---
        
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
                    order.status = Order.OrderStatus.READY_FOR_PICKUP
                    order.save(update_fields=['status'])

                    delivery = order.delivery
                    delivery.status = Delivery.DeliveryStatus.PENDING_ACCEPTANCE
                    delivery.save(update_fields=['status'])

                    delivery_object_for_notification = delivery 
                    logger.info(f"Order {order.order_id} is now READY_FOR_PICKUP.") # <-- CHANGED

            # Transaction ke BAAD
            if delivery_object_for_notification:
                try:
                    # --- UPDATED CALL ---
                    notify_nearby_riders(
                        delivery_object_for_notification, 
                        context={'request': request}
                    )
                except Exception as e:
                    logger.error(f"PickTaskCompleteView: Error calling notify_nearby_riders for order {order.order_id}: {e}") # <-- CHANGED
                    pass # Helper function ab errors ko internally log karta hai

            serializer = self.get_serializer(task)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except WmsStock.DoesNotExist:
             logger.warning(f"PickTaskComplete FAILED: WmsStock not found for task {pk}") # <-- ADDED
             return Response(
                {"error": "Stock item not found at the specified location."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"PickTaskComplete FAILED for task {pk}: {str(e)}") # <-- ADDED
            return Response(
                {"error": f"Failed to complete task: {str(e)}"}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        

class PickTaskReportIssueView(generics.GenericAPIView):
    """
    API: POST /api/wms/pick-tasks/<int:pk>/report-issue/
    Picker ko ek task par issue (e.g., "item nahi mila") report karne deta hai.
    """
    permission_classes = [IsStorePicker]
    serializer_class = PickTaskReportIssueSerializer # Input serializer

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get('pk')
        try:
            task = PickTask.objects.get(
                id=pk,
                assigned_to=request.user,
                status=PickTask.PickStatus.PENDING # Sirf PENDING task ko report kar sakte hain
            )
        except PickTask.DoesNotExist:
            return Response(
                {"error": "Task not found or is not pending."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Task ko 'ISSUE' mark karein aur notes save karein
        with transaction.atomic():
            task.status = PickTask.PickStatus.ISSUE
            task.picker_notes = serializer.validated_data['notes']
            task.save(update_fields=['status', 'picker_notes', 'updated_at'])

        logger.info(f"Picker {request.user.username} reported issue on Task {task.id}: {task.picker_notes}") # <-- CHANGED

        # Response mein updated task bhejein
        response_serializer = PickTaskSerializer(task, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)
    

class RequestNewTaskView(generics.GenericAPIView):
    """
    API: POST /api/wms/request-new-task/
    Picker ko ek naya unassigned task "pull" (request) karne deta hai.
    """
    permission_classes = [IsStorePicker]
    serializer_class = PickTaskSerializer # Response ke liye

    def post(self, request, *args, **kwargs):
        picker_profile = request.user.store_staff_profile
        store = picker_profile.store

        try:
            with transaction.atomic():
                # 1. Store ke sabse puraane unassigned task ko dhoondein aur lock karein
                # 'select_for_update(skip_locked=True)' ka matlab hai ki agar do picker
                # ek hi samay par request karte hain, toh ek ko task milega aur doosre
                # ko agla task milega (ya error nahi aayega).
                task = PickTask.objects.select_for_update(skip_locked=True).filter(
                    order__store=store,
                    status=PickTask.PickStatus.PENDING,
                    assigned_to__isnull=True # <-- Main logic
                ).order_by('created_at').first() # Sabse puraana task

                if not task:
                    # Agar koi unassigned task nahi mila
                    return Response(
                        {"message": "No unassigned tasks available."},
                        status=status.HTTP_200_OK
                    )
                
                # 2. Task ko is picker ko assign karein
                task.assigned_to = request.user
                task.save(update_fields=['assigned_to', 'updated_at'])
                
                # 3. Picker ka 'last_task_assigned_at' update karein
                picker_profile.last_task_assigned_at = timezone.now()
                picker_profile.save(update_fields=['last_task_assigned_at'])
            
            # 4. Success response (poora task detail bhejein)
            logger.info(f"Task {task.id} auto-assigned to picker {request.user.username}") # <-- CHANGED
            serializer = self.get_serializer(task, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        except Exception as e:
            # Shayad 'skip_locked=True' ki wajah se ya koi aur error
            logger.warning(f"Error during new task request for {request.user.username}: {e}") # <-- CHANGED
            return Response(
                {"error": "Could not assign task, please try again."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE # 503 matlab "thodi der baad try karo"
            )