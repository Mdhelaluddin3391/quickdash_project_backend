from django.urls import re_path
from . import consumers

websocket_urlpatterns = [

    re_path(r'ws/delivery/notifications/$', consumers.RiderNotificationConsumer.as_asgi()),

    re_path(r'ws/track/(?P<order_id>[\w-]+)/$', consumers.CustomerTrackingConsumer.as_asgi()),
]