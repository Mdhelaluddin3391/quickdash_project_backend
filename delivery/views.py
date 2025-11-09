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
from django.db.models import F
from orders.models import Order, Payment
from .models import RiderProfile, Delivery
from .serializers import (
    RiderProfileDetailSerializer,
    RiderProfileUpdateSerializer,
    RiderLocationUpdateSerializer,
    RiderDeliverySerializer,
    DeliveryUpdateSerializer,
    StaffOrderStatusUpdateSerializer,
    RiderEarningSerializer
)
from django.db.models import Sum, Count, Q # <-- Q import kiya (Task 1 se)
from decimal import Decimal # <-- Decimal import kiya (Task 1 se)
from django.db.models import Sum, Count, Q # <-- 'Q' import karein
from decimal import Decimal # <-- 'Decimal' import karein (agar nahi hai toh)
from .models import RiderProfile, Delivery, RiderEarning # <-- NAYA IMPORT
from django.db.models import Sum, Count # <-- NAYA IMPORT
from django.db.models.functions import TruncDay # <-- NAYA IMPORT
from datetime import timedelta # <-- NAYA IMPORT
from django.contrib.gis.measure import D  # <-- YEH NAYI LINE ADD KAREIN
from rest_framework import generics, status
from orders.models import Order
from orders.serializers import OrderDetailSerializer
from accounts.permissions import IsRider, IsStoreStaff






class RiderEarningsView(generics.GenericAPIView):
    """
    API: GET /api/delivery/earnings/
    Rider ki total kamai aur daily breakdown dikhata hai.
    Query Params:
    - ?filter=today (Sirf aaj ki kamai)
    - ?filter=weekly (Pichle 7 din ki kamai)
    - (default) Poori list (paginated)
    """
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderEarningSerializer

    def get(self, request, *args, **kwargs):
        rider_profile = request.user.rider_profile
        queryset = RiderEarning.objects.filter(rider=rider_profile)
        
        filter_param = request.query_params.get('filter')
        today = timezone.now().date()
        
        if filter_param == 'today':
            queryset = queryset.filter(created_at__date=today)
        elif filter_param == 'weekly':
            week_ago = today - timedelta(days=7)
            queryset = queryset.filter(created_at__date__gte=week_ago)
        
        # Kul kamai calculate karein
        total_stats = queryset.aggregate(
            total_deliveries=Count('id'),
            total_earnings=Sum('total_earning'),
            total_tips=Sum('tip')
        )
        
        # Daily breakdown (filtered queryset par)
        daily_summary = queryset.annotate(
            day=TruncDay('created_at')
        ).values('day').annotate(
            deliveries=Count('id'),
            earnings=Sum('total_earning')
        ).order_by('-day')
        
        # Individual earning list (paginated)
        page = self.paginate_queryset(queryset.order_by('-created_at'))
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            # Paginated response se data nikaalein (next, previous, count, results)
            paginated_data = serializer.data
            
            response_data = {
                'total_stats': total_stats,
                'daily_summary': list(daily_summary),
                'recent_earnings_list': paginated_data # 'results' key paginated response mein hoti hai
            }
            # get_paginated_response poora response object return karta hai
            return self.get_paginated_response(response_data)

        # Agar pagination nahi hai (ya default settings mein nahi hai)
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'total_stats': total_stats,
            'daily_summary': list(daily_summary),
            'recent_earnings_list': serializer.data
        })
# --- END NAYA VIEW ---




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
            # Hum order ko bhi prefetch kar rahe hain
            delivery = get_object_or_404(
                Delivery.objects.select_related('order'), 
                id=delivery_id, 
                rider=rider_profile
            )
            
            current_status = delivery.status
            
            if current_status == Delivery.DeliveryStatus.ACCEPTED and \
               new_status == Delivery.DeliveryStatus.AT_STORE:
                
                delivery.at_store_at = timezone.now()
                delivery.status = new_status
                delivery.save() # Earning logic ke liye save() call zaroori hai
            
            elif current_status == Delivery.DeliveryStatus.AT_STORE and \
                 new_status == Delivery.DeliveryStatus.PICKED_UP:
                
                delivery.picked_up_at = timezone.now()
                delivery.status = new_status
                delivery.save()
            
            elif current_status == Delivery.DeliveryStatus.PICKED_UP and \
                 new_status == Delivery.DeliveryStatus.DELIVERED:
                
                # --- NAYA COD LOGIC ---
                # Hum transaction ka istemaal karenge
                with transaction.atomic():
                    # 1. Delivery object ko update karein
                    delivery.delivered_at = timezone.now()
                    delivery.status = new_status
                    
                    order = delivery.order
                    
                    # 2. Check karein ki yeh unpaid COD order hai ya nahi
                    if order.payment_status == Order.PaymentStatus.PENDING:
                        
                        # Hum lock laga kar payment object nikaalenge
                        payment = order.payments.select_for_update().first()
                        
                        if payment and payment.payment_method == Payment.PaymentMethod.COD:
                            
                            # 3. Payment ko SUCCESSFUL mark karein
                            payment.status = Order.PaymentStatus.SUCCESSFUL
                            payment.save(update_fields=['status'])
                            
                            # 4. Order ko SUCCESSFUL mark karein
                            # (hum order par lock nahi laga rahe kyunki payment par hai)
                            order.payment_status = Order.PaymentStatus.SUCCESSFUL
                            order.save(update_fields=['payment_status'])
                            
                            # 5. Rider ka cash_on_hand update karein
                            # (RiderProfile object pehle hi 'rider_profile' variable mein hai)
                            rider_profile.cash_on_hand = F('cash_on_hand') + order.final_total
                            rider_profile.save(update_fields=['cash_on_hand'])
                            
                            print(f"COD Payment for Order {order.order_id} (₹{order.final_total}) confirmed.")
                            print(f"Rider {rider_profile.user.username} cash on hand updated.")

                    # 6. Ab delivery.save() call karein
                    # Yeh `save()` method trigger hoga, jo automatically `RiderEarning` create karega
                    delivery.save()
                # --- END NAYA COD LOGIC ---
            
            else:
                return Response(
                    {"error": f"Invalid status transition from '{current_status}' to '{new_status}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # (Puraana delivery.save() call ab transaction ke andar hai)

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

            # --- NAYA OPTIMIZED NOTIFICATION LOGIC ---
            try:
                store_location = order.store.location
                if not store_location:
                    raise Exception("Store ki location set nahi hai.")

                # Step 1: Store ke 10km ke daayre mein available riders dhoondein
                nearby_available_riders = RiderProfile.objects.filter(
                    is_online=True,
                    on_delivery=False,
                    current_location__isnull=False,
                    # D(km=10) = 10 kilometer
                    current_location__distance_lte=(store_location, D(km=10)) 
                ).annotate(
                    # Store se distance calculate karein
                    distance_to_store=Distance('current_location', store_location)
                ).order_by(
                    'distance_to_store' # Sabse nazdeek wala rider sabse pehle
                )[:10] # Sirf top 10 ko bhejein

                if not nearby_available_riders.exists():
                    print(f"Order {order.order_id} READY, lekin koi nearby rider available nahi hai.")
                
                
                else:
                    channel_layer = get_channel_layer()
                    delivery_data = RiderDeliverySerializer(delivery, context={'request': request}).data
                    
                    # Step 2: Sirf nearby riders ko unke personal group mein notification bhejein
                    for rider in nearby_available_riders:
                        group_name = f"rider_{rider.id}"
                        async_to_sync(channel_layer.group_send)(
                            group_name,
                            {
                                "type": "new.delivery.notification", 
                                "delivery": delivery_data
                            }
                        )
                    
                    print(f"Order {order.order_id} READY. Notified {len(nearby_available_riders)} nearby riders.")

            except Exception as e:
                print(f"Error sending channel notification: {e}")
            # --- END NAYA LOGIC ---

            return Response(
                OrderDetailSerializer(order, context={'request': request}).data,
                status=status.HTTP_200_OK
            )



class RiderEarningsView(generics.GenericAPIView):
    """
    API: GET /api/delivery/earnings/
    Rider ki total kamai aur daily breakdown dikhata hai.
    Query Params:
    - ?filter=today (Sirf aaj ki kamai)
    - ?filter=weekly (Pichle 7 din ki kamai)
    - (default) Poori list (paginated)
    """
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderEarningSerializer

    def get(self, request, *args, **kwargs):
        rider_profile = request.user.rider_profile
        queryset = RiderEarning.objects.filter(rider=rider_profile)
        
        filter_param = request.query_params.get('filter')
        today = timezone.now().date()
        
        if filter_param == 'today':
            queryset = queryset.filter(created_at__date=today)
        elif filter_param == 'weekly':
            week_ago = today - timedelta(days=7)
            queryset = queryset.filter(created_at__date__gte=week_ago)
        
        # --- NAYA AGGREGATION LOGIC ---
        
        # Kul kamai (poore filtered queryset par)
        total_stats = queryset.aggregate(
            total_deliveries=Count('id'),
            total_earnings=Sum('total_earning'),
            total_tips=Sum('tip')
        )
        
        # Kul kitna paisa milna baaki hai (sirf UNPAID earnings)
        # Yeh filter_param se affect nahi hona chahiye, isliye poore queryset par
        unpaid_stats = RiderEarning.objects.filter(
            rider=rider_profile, 
            status=RiderEarning.EarningStatus.UNPAID
        ).aggregate(
            total_unpaid=Sum('total_earning'),
            unpaid_deliveries_count=Count('id')
        )

        # total_stats dictionary ko update karein
        total_stats.update({
            'total_unpaid': unpaid_stats.get('total_unpaid') or Decimal('0.00'),
            'unpaid_deliveries_count': unpaid_stats.get('unpaid_deliveries_count') or 0
        })
        # --- END NAYA LOGIC ---

        # Daily breakdown (filtered queryset par)
        daily_summary = queryset.annotate(
            day=TruncDay('created_at')
        ).values('day').annotate(
            deliveries=Count('id'),
            earnings=Sum('total_earning')
        ).order_by('-day')
        
        # Individual earning list (paginated, filtered queryset par)
        page = self.paginate_queryset(queryset.order_by('-created_at'))
        
        # Paginated response
        serializer = self.get_serializer(page, many=True)
        
        # get_paginated_response ek poora Response object return karta hai
        # Humein uske data mein total_stats add karna hai
        paginated_response_data = self.get_paginated_response(serializer.data).data
        
        # Naya response data banayein
        response_data = {
            'total_stats': total_stats,
            'daily_summary': list(daily_summary),
            'recent_earnings_list': paginated_response_data # Yeh 'results', 'next', 'previous' sab le aayega
        }
        
        return Response(response_data)