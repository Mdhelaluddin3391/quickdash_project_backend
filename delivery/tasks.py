# quickdash_project_backend/delivery/tasks.py

import logging # <-- ADD
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings # <-- Naya import

from .models import Delivery, RiderProfile
from .serializers import RiderDeliverySerializer

# Setup logger
logger = logging.getLogger(__name__) # <-- ADD


@shared_task(name="retry_unassigned_deliveries")
def retry_unassigned_deliveries():
    """
    Har minute chalta hai.
    Unn orders ko dhoondhta hai jo 1 minute se zyada se 'PENDING_ACCEPTANCE' 
    mein phase hue hain aur unke liye dobara riders ko notify karta hai.
    """
    
    # Aise orders dhoondein jo 1 min pehle update hue the
    # aur abhi tak PENDING_ACCEPTANCE mein hain
    time_threshold = timezone.now() - timedelta(minutes=1)
    
    stuck_deliveries = Delivery.objects.filter(
        status=Delivery.DeliveryStatus.PENDING_ACCEPTANCE,
        rider__isnull=True,
        updated_at__lt=timezone.now() - timedelta(minutes=1)
    ).select_related('order__store', 'order__store__location')


    if not stuck_deliveries.exists():
        logger.info(f"CELERY TASK (retry_unassigned): No stuck deliveries found. All good.") # <-- CHANGED
        return "No stuck deliveries found."

    logger.info(f"CELERY TASK (retry_unassigned): Found {stuck_deliveries.count()} stuck deliveries. Retrying...") # <-- CHANGED
    
    channel_layer = get_channel_layer()
    
    # Har stuck delivery ke liye, nazdeeki riders dhoondein
    for delivery in stuck_deliveries:
        store_location = delivery.order.store.location
        if not store_location:
            continue

        # FIX: Hardcoded 10km ko settings se replace kiya
        nearby_available_riders = RiderProfile.objects.filter(
            user__is_active=True,  # <-- YEH NAYA CHECK ADD HUA
            is_online=True,
            on_delivery=False,
            current_location__isnull=False,
            current_location__distance_lte=(store_location, D(km=settings.RIDER_SEARCH_RADIUS_KM)) 
        ).annotate(
            distance_to_store=Distance('current_location', store_location)
        ).order_by('distance_to_store')[:10]

        if not nearby_available_riders.exists():
            logger.warning(f"RETRY: Order {delivery.order.order_id} stuck, but still no riders nearby.") # <-- CHANGED
            continue

        # Delivery data serialize karein
        # Serializer context ke bina media URL nahi bana payega, par data bhej dega
        delivery_data = RiderDeliverySerializer(delivery).data
        
        for rider in nearby_available_riders:
            group_name = f"rider_{rider.id}"
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": "new.delivery.notification", 
                    "delivery": delivery_data
                }
            )
        
        logger.info(f"RETRY: Notified {len(nearby_available_riders)} riders for stuck order {delivery.order.order_id}") # <-- CHANGED
        
        # Delivery ka updated_at timestamp update karein
        # taaki yeh agle 1 min tak dobara check na ho
        delivery.save(update_fields=['updated_at'])

    return f"Retried {stuck_deliveries.count()} deliveries."