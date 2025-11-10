import logging
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance

from .models import RiderProfile
from .serializers import RiderDeliverySerializer

# Ek logger setup karein
logger = logging.getLogger(__name__)

def notify_nearby_riders(delivery_object, request_context=None):
    """
    Ek helper function jo ek 'PENDING_ACCEPTANCE' delivery ke liye
    nearby available riders ko WebSocket notification bhejta hai.
    """
    try:
        order = delivery_object.order
        store_location = order.store.location
        
        if not store_location:
            raise Exception("Store ki location set nahi hai.")

        nearby_available_riders = RiderProfile.objects.filter(
            user__is_active=True,
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
            logger.info(f"Order {order.order_id} READY, lekin koi nearby rider available nahi hai.")
            return

        channel_layer = get_channel_layer()
        
        context = {}
        if request_context:
            context = request_context

        delivery_data = RiderDeliverySerializer(
            delivery_object, 
            context=context
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
        
        logger.info(f"Order {order.order_id} READY. Notified {len(nearby_available_riders)} nearby riders.")

    except Exception as e:
        logger.error(f"CRITICAL: Order {delivery_object.order.order_id} ready, but failed to send rider notification: {e}")