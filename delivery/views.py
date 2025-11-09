# delivery/views.py
from django.db import transaction
from django.utils import timezone
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from rest_framework import generics, status, mixins # <-- 'mixins' add karein
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import F, Sum, Count, Q
from django.db.models.functions import TruncDay
from decimal import Decimal
from datetime import timedelta
from django.contrib.gis.measure import D
from django.conf import settings
from rest_framework.exceptions import NotFound # <-- Naya Import
from rest_framework.parsers import MultiPartParser, FormParser # <-- Naya Import

# Model Imports
from orders.models import Order, Payment
from .models import RiderProfile, Delivery, RiderEarning, RiderCashDeposit
from .models import RiderApplication, RiderDocument # <-- NAYE MODELS

# Serializer Imports
from .serializers import (
    RiderProfileDetailSerializer,
    RiderProfileUpdateSerializer,
    RiderLocationUpdateSerializer,
    RiderDeliverySerializer,
    DeliveryUpdateSerializer,
    StaffOrderStatusUpdateSerializer,
    RiderEarningSerializer,
    RiderCashDepositSerializer,
    RiderApplicationSerializer,           # <-- NAYA
    RiderApplicationCreateSerializer,   # <-- NAYA
    RiderDocumentUploadSerializer       # <-- NAYA
)
from orders.serializers import OrderDetailSerializer

# Permission Imports
from accounts.permissions import IsRider, IsStoreStaff

# Helper Function import
from .utils import notify_nearby_riders


class RiderProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, IsRider]
    def get_serializer_class(self):
        if self.request.method == 'GET':
            return RiderProfileDetailSerializer
        return RiderProfileUpdateSerializer
    def get_object(self):
        profile, created = RiderProfile.objects.get_or_create(user=self.request.user)
        return profile

class RiderLocationUpdateView(generics.UpdateAPIView):
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
        except Delivery.DoesNotExist:
            pass # No active delivery
        except Exception as e:
            print(f"Error broadcasting location: {e}")
        return Response({"success": "Location updated successfully."}, status=status.HTTP_200_OK)

class AvailableDeliveryListView(generics.ListAPIView):
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

class UpdateDeliveryStatusView(generics.GenericAPIView):
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
                Delivery.objects.select_related('order'), 
                id=delivery_id, 
                rider=rider_profile
            )
            current_status = delivery.status
            
            if current_status == Delivery.DeliveryStatus.ACCEPTED and \
               new_status == Delivery.DeliveryStatus.AT_STORE:
                delivery.at_store_at = timezone.now()
                delivery.status = new_status
                delivery.save()
            
            elif current_status == Delivery.DeliveryStatus.AT_STORE and \
                 new_status == Delivery.DeliveryStatus.PICKED_UP:
                delivery.picked_up_at = timezone.now()
                delivery.status = new_status
                delivery.save()
            
            elif current_status == Delivery.DeliveryStatus.PICKED_UP and \
                 new_status == Delivery.DeliveryStatus.DELIVERED:
                with transaction.atomic():
                    delivery.delivered_at = timezone.now()
                    delivery.status = new_status
                    order = delivery.order
                    
                    if order.payment_status == Order.PaymentStatus.PENDING:
                        payment = order.payments.select_for_update().first()
                        if payment and payment.payment_method == Payment.PaymentMethod.COD:
                            payment.status = Order.PaymentStatus.SUCCESSFUL
                            payment.save(update_fields=['status'])
                            order.payment_status = Order.PaymentStatus.SUCCESSFUL
                            order.save(update_fields=['payment_status'])
                            rider_profile.cash_on_hand = F('cash_on_hand') + order.final_total
                            rider_profile.save(update_fields=['cash_on_hand'])
                    delivery.save() # RiderEarning create karne ke liye
            else:
                return Response(
                    {"error": f"Invalid status transition from '{current_status}' to '{new_status}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            serializer = RiderDeliverySerializer(delivery)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class CurrentDeliveryDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderDeliverySerializer
    def get_object(self):
        try:
            return Delivery.objects.get(
                rider=self.request.user.rider_profile,
                status__in=[
                    Delivery.DeliveryStatus.ACCEPTED,
                    Delivery.DeliveryStatus.AT_STORE,
                    Delivery.DeliveryStatus.PICKED_UP
                ]
            )
        except Delivery.DoesNotExist:
            return None
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance is None:
            return Response({"message": "No active delivery found."}, status=status.HTTP_200_OK)
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

class StaffNewOrderListView(generics.ListAPIView):
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
    --- (UPDATED: Ab helper function use karta hai) ---
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
            order = Order.objects.get(order_id=order_id, store=staff_profile.store)
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
                # --- UPDATED CALL ---
                notify_nearby_riders(delivery, context={'request': request})
            except Exception as e:
                print(f"Error sending channel notification: {e}")

            return Response(
                OrderDetailSerializer(order, context={'request': request}).data,
                status=status.HTTP_200_OK
            )
        
        return Response({"error": "Invalid status transition."}, status=status.HTTP_400_BAD_REQUEST)

class RiderEarningsView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderEarningSerializer
    def get(self, request, *args, **kwargs):
        rider_profile = request.user.rider_profile
        base_queryset = RiderEarning.objects.filter(rider=rider_profile)
        filter_param = request.query_params.get('filter')
        today = timezone.now().date()
        filtered_queryset = base_queryset
        
        if filter_param == 'today':
            filtered_queryset = base_queryset.filter(created_at__date=today)
        elif filter_param == 'weekly':
            week_ago = today - timedelta(days=7)
            filtered_queryset = base_queryset.filter(created_at__date__gte=week_ago)
        
        total_stats = filtered_queryset.aggregate(
            total_deliveries=Count('id'),
            total_earnings=Sum('total_earning'),
            total_tips=Sum('tip')
        )
        unpaid_stats = base_queryset.filter(
            status=RiderEarning.EarningStatus.UNPAID
        ).aggregate(
            total_unpaid=Sum('total_earning'),
            unpaid_deliveries_count=Count('id')
        )
        total_stats.update({
            'total_unpaid': unpaid_stats.get('total_unpaid') or Decimal('0.00'),
            'unpaid_deliveries_count': unpaid_stats.get('unpaid_deliveries_count') or 0,
            'total_deliveries': total_stats.get('total_deliveries') or 0,
            'total_earnings': total_stats.get('total_earnings') or Decimal('0.00'),
            'total_tips': total_stats.get('total_tips') or Decimal('0.00'),
        })
        daily_summary = filtered_queryset.annotate(
            day=TruncDay('created_at')
        ).values('day').annotate(
            deliveries=Count('id'),
            earnings=Sum('total_earning')
        ).order_by('-day')
        
        page = self.paginate_queryset(filtered_queryset.order_by('-created_at'))
        serializer = self.get_serializer(page, many=True)
        paginated_response_data = self.get_paginated_response(serializer.data).data
        
        response_data = {
            'total_stats': total_stats,
            'daily_summary': list(daily_summary),
            'recent_earnings_list': paginated_response_data
        }
        return Response(response_data)

class RiderCashDepositView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsRider]
    serializer_class = RiderCashDepositSerializer
    def get_queryset(self):
        return RiderCashDeposit.objects.filter(
            rider=self.request.user.rider_profile
        ).order_by('-created_at')
    def perform_create(self, serializer):
        serializer.save(
            rider=self.request.user.rider_profile,
            status=RiderCashDeposit.DepositStatus.PENDING
        )



class RiderApplicationView(mixins.RetrieveModelMixin,
                           mixins.CreateModelMixin,
                           generics.GenericAPIView):
    """
    API: GET, POST /api/delivery/apply/
    GET: User ki current application ka status dikhata hai.
    POST: Rider banne ke liye ek nayi application submit karta hai.
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return RiderApplicationCreateSerializer # Input ke liye
        return RiderApplicationSerializer # Output ke liye

    def get_object(self):
        # GET request ke liye
        if hasattr(self.request.user, 'rider_profile'):
            raise NotFound("Aap pehle se hi ek registered rider hain.")
        
        try:
            # User ki application dhoondein
            return RiderApplication.objects.prefetch_related('documents').get(user=self.request.user)
        except RiderApplication.DoesNotExist:
            raise NotFound("Aapne abhi tak application submit nahi ki hai.")
    
    def get(self, request, *args, **kwargs):
        """GET request ko handle karta hai (Status check)"""
        return self.retrieve(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        """POST request ko handle karta hai (Nayi application)"""
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        # Application create karte waqt user aur default status set karein
        serializer.save(
            user=self.request.user,
            status=RiderApplication.ApplicationStatus.PENDING
        )

class RiderDocumentUploadView(generics.CreateAPIView):
    """
    API: POST /api/delivery/apply/upload-document/
    Ek maujooda 'PENDING' application ke liye document upload karta hai.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = RiderDocumentUploadSerializer
    # File upload ke liye yeh parser zaroori hain
    parser_classes = [MultiPartParser, FormParser]

    def create(self, request, *args, **kwargs):
        # Check karein ki user pehle se rider toh nahi hai
        if hasattr(request.user, 'rider_profile'):
            return Response(
                {"error": "Aap pehle se hi ek registered rider hain."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Baaki validation (application hai ya nahi, etc.) serializer karega
        return super().create(request, *args, **kwargs)