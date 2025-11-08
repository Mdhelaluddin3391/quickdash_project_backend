from django.db import transaction
from django.utils import timezone
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import RiderProfile, Delivery
from .serializers import (
    RiderProfileDetailSerializer,
    RiderProfileUpdateSerializer,
    RiderLocationUpdateSerializer,
    RiderDeliverySerializer,
    DeliveryUpdateSerializer,
    StaffOrderStatusUpdateSerializer
)
from orders.models import Order
from orders.serializers import OrderDetailSerializer
from accounts.permissions import IsRider, IsStoreStaff

class RiderProfileView(generics.RetrieveUpdateAPIView):
    """
    API: GET, PATCH /api/delivery/profile/
    Rider ki profile (online status, vehicle) manage karta hai.
    """
    permission_classes = [IsAuthenticated, IsRider]
    
    def get_serializer_class(self):
        if self.request.method == 'GET':
            return RiderProfileDetailSerializer
        return RiderProfileUpdateSerializer

    def get_object(self):
        profile, created = RiderProfile.objects.get_or_create(user=self.request.user)
        return profile

class RiderLocationUpdateView(generics.UpdateAPIView):
    """
    API: PATCH /api/delivery/profile/update-location/
    Rider ki live location (lat/lng) update karta hai.
    """
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderLocationUpdateSerializer

    def get_object(self):
        profile, created = RiderProfile.objects.get_or_create(user=self.request.user)
        return profile

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data) 
        serializer.is_valid(raise_exception=True)
        updated_location_data = serializer.save()

        try:
            active_delivery = Delivery.objects.get(
                rider=instance,
                status__in=[
                    Delivery.DeliveryStatus.ACCEPTED,
                    Delivery.DeliveryStatus.AT_STORE,
                    Delivery.DeliveryStatus.PICKED_UP
                ]
            )
            if active_delivery:
                    order_id = active_delivery.order.order_id
                    group_name = f"order_{order_id}"
                    
                    channel_layer = get_channel_layer()
                    
                    location_payload = {
                        'latitude': updated_location_data.current_location.y,
                        'longitude': updated_location_data.current_location.x
                    }
                    
                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        {
                            "type": "rider.location.update", 
                            "location": location_payload
                        }
                    )
                    print(f"Sent location update to group '{group_name}'")

        except Delivery.DoesNotExist:
            print("Rider location updated, but no active delivery found. Skipping broadcast.")
        except Exception as e:
            print(f"Error broadcasting location: {e}")

        return Response({"success": "Location updated successfully."}, status=status.HTTP_200_OK)

class AvailableDeliveryListView(generics.ListAPIView):
    """
    API: GET /api/delivery/available/
    Rider ke liye sabhi available deliveries ki list.
    """
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderDeliverySerializer

    def get_queryset(self):
        rider_profile = self.request.user.rider_profile
        
        queryset = Delivery.objects.filter(
            status=Delivery.DeliveryStatus.PENDING_ACCEPTANCE,
            rider__isnull=True
        ).select_related(
            'order__store', 
            'order__delivery_address',
            'order__user'
        ).prefetch_related('order__payments')
        
        if rider_profile.current_location:
            queryset = queryset.annotate(
                distance_to_store=Distance('order__store__location', rider_profile.current_location)
            ).order_by('distance_to_store', 'created_at')
        else:
            queryset = queryset.order_by('created_at')
            
        return queryset

class AcceptDeliveryView(generics.GenericAPIView):
    """
    API: POST /api/delivery/<int:pk>/accept/
    Rider ek available delivery ko accept karta hai.
    """
    permission_classes = [IsAuthenticated, IsRider]

    def post(self, request, *args, **kwargs):
        delivery_id = self.kwargs.get('pk')
        rider_profile = request.user.rider_profile
        
        if rider_profile.on_delivery:
            return Response(
                {"error": "You are already on an active delivery."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                delivery = Delivery.objects.select_for_update().get(
                    id=delivery_id, 
                    status=Delivery.DeliveryStatus.PENDING_ACCEPTANCE,
                    rider__isnull=True
                )
                
                delivery.rider = rider_profile
                delivery.status = Delivery.DeliveryStatus.ACCEPTED
                delivery.accepted_at = timezone.now()
                delivery.save() 
            
            serializer = RiderDeliverySerializer(delivery)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except Delivery.DoesNotExist:
            return Response(
                {"error": "Delivery not available or already taken."}, 
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class UpdateDeliveryStatusView(generics.GenericAPIView):
    """
    API: POST /api/delivery/<int:pk>/update-status/
    Rider delivery ka status update karta hai (AT_STORE, PICKED_UP, DELIVERED).
    """
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = DeliveryUpdateSerializer

    def post(self, request, *args, **kwargs):
        delivery_id = self.kwargs.get('pk')
        rider_profile = request.user.rider_profile
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']
        
        try:
            delivery = get_object_or_404(
                Delivery, 
                id=delivery_id, 
                rider=rider_profile
            )
            
            current_status = delivery.status
            
            if current_status == Delivery.DeliveryStatus.ACCEPTED and \
               new_status == Delivery.DeliveryStatus.AT_STORE:
                delivery.at_store_at = timezone.now()
            
            elif current_status == Delivery.DeliveryStatus.AT_STORE and \
                 new_status == Delivery.DeliveryStatus.PICKED_UP:
                delivery.picked_up_at = timezone.now()
            
            elif current_status == Delivery.DeliveryStatus.PICKED_UP and \
                 new_status == Delivery.DeliveryStatus.DELIVERED:
                delivery.delivered_at = timezone.now()
            
            else:
                return Response(
                    {"error": f"Invalid status transition from '{current_status}' to '{new_status}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            delivery.status = new_status
            delivery.save()
            
            serializer = RiderDeliverySerializer(delivery)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CurrentDeliveryDetailView(generics.RetrieveAPIView):
    """
    API: GET /api/delivery/current/
    Rider ki current active delivery ki details.
    """
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderDeliverySerializer

    def get_object(self):
        try:
            delivery = Delivery.objects.get(
                rider=self.request.user.rider_profile,
                status__in=[
                    Delivery.DeliveryStatus.ACCEPTED,
                    Delivery.DeliveryStatus.AT_STORE,
                    Delivery.DeliveryStatus.PICKED_UP
                ]
            )
            return delivery
        except Delivery.DoesNotExist:
            return None
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance is None:
            return Response({"message": "No active delivery found."}, status=status.HTTP_200_OK)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)



class StaffNewOrderListView(generics.ListAPIView):
    """
    API: GET /api/delivery/staff/new-orders/
    Store staff ko unke store ke naye (CONFIRMED) orders dikhata hai.
    """
    permission_classes = [IsAuthenticated, IsStoreStaff]
    serializer_class = OrderDetailSerializer 
    def get_queryset(self):
        staff_profile = self.request.user.store_staff_profile
        store = staff_profile.store
        
        if not store:
            return Order.objects.none()

        return Order.objects.filter(
            store=store,
            status=Order.OrderStatus.CONFIRMED
        ).prefetch_related(
            'items', 
            'items__inventory_item__variant__product'
        ).order_by('created_at')


class StaffUpdateOrderStatusView(generics.GenericAPIView):
    """
    API: POST /api/delivery/staff/order/<order_id>/update-status/
    Staff ko order ka status (PREPARING ya READY_FOR_PICKUP) update karne deta hai.
    """
    permission_classes = [IsAuthenticated, IsStoreStaff]
    serializer_class = StaffOrderStatusUpdateSerializer
    lookup_field = 'order_id'

    def post(self, request, *args, **kwargs):
        order_id = self.kwargs.get('order_id')
        staff_profile = request.user.store_staff_profile

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        try:
            order = Order.objects.get(
                order_id=order_id,
                store=staff_profile.store
            )
            delivery = Delivery.objects.get(order=order) 

        except (Order.DoesNotExist, Delivery.DoesNotExist):
            return Response({"error": "Order not found at your store."}, status=status.HTTP_404_NOT_FOUND)

        
        if new_status == Order.OrderStatus.PREPARING and \
           order.status == Order.OrderStatus.CONFIRMED:
            
            with transaction.atomic():
                order.status = Order.OrderStatus.PREPARING
                order.save()
                

            
            return Response(
                OrderDetailSerializer(order, context={'request': request}).data, 
                status=status.HTTP_200_OK
            )

        elif new_status == Order.OrderStatus.READY_FOR_PICKUP and \
             order.status == Order.OrderStatus.PREPARING:
            
            with transaction.atomic():
                order.status = Order.OrderStatus.READY_FOR_PICKUP
                order.save()
                
                delivery.status = Delivery.DeliveryStatus.PENDING_ACCEPTANCE
                delivery.save()

            try:
                channel_layer = get_channel_layer()
                delivery_data = RiderDeliverySerializer(delivery, context={'request': request}).data
                
                async_to_sync(channel_layer.group_send)(
                    "online_riders",
                    {
                        "type": "new.delivery.notification", 
                        "delivery": delivery_data
                    }
                )
                print(f"Order {order.order_id} is READY. Notifying 'online_riders'.")
            except Exception as e:
                print(f"Error sending channel notification: {e}")

            return Response(
                OrderDetailSerializer(order, context={'request': request}).data,
                status=status.HTTP_200_OK
            )

        return Response(
            {"error": f"Invalid status transition from '{order.status}' to '{new_status}'."},
            status=status.HTTP_400_BAD_REQUEST
        )