import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack 
import delivery.routing 

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quickdash.settings')

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,


    "websocket": AuthMiddlewareStack( 
        URLRouter(
            delivery.routing.websocket_urlpatterns 
        )
    ),
})