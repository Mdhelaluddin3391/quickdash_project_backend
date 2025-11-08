from rest_framework import serializers
from django.contrib.gis.geos import Point
from .models import RiderProfile, Delivery
from orders.models import Order
from accounts.serializers import AddressSerializer
from store.serializers import StoreSerializer
from django.contrib.gis.measure import Distance


class RiderProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Rider ko apni profile (online status, vehicle) update karne ke liye.
    """
    class Meta:
        model = RiderProfile
        fields = [
            'is_online', 
            'vehicle_details'
        ]

class RiderLocationUpdateSerializer(serializers.Serializer):
    """
    Rider se Latitude/Longitude input lene ke liye.
    """
    latitude = serializers.FloatField(required=True)
    longitude = serializers.FloatField(required=True)

    def update(self, instance, validated_data):
        instance.current_location = Point(
            validated_data['longitude'], 
            validated_data['latitude'], 
            srid=4326
        )
        instance.save()
        return instance

class RiderProfileDetailSerializer(serializers.ModelSerializer):
    """
    Rider ki poori profile dikhane ke liye.
    """
    username = serializers.CharField(source='user.username', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    
    current_location_coords = serializers.SerializerMethodField()

    class Meta:
        model = RiderProfile
        fields = [
            'username', 
            'phone_number', 
            'is_online', 
            'on_delivery',
            'vehicle_details',
            'rating',
            'current_location_coords'
        ]
        read_only_fields = ['username', 'phone_number', 'on_delivery', 'rating', 'current_location_coords']

    def get_current_location_coords(self, obj):
        if obj.current_location:
            return {'latitude': obj.current_location.y, 'longitude': obj.current_location.x}
        return None


class DeliveryUpdateSerializer(serializers.Serializer):
    """
    Rider se agla status lene ke liye.
    """
    status = serializers.ChoiceField(
        choices=[
            Delivery.DeliveryStatus.AT_STORE, 
            Delivery.DeliveryStatus.PICKED_UP, 
            Delivery.DeliveryStatus.DELIVERED
        ],
        required=True
    )

class RiderDeliverySerializer(serializers.ModelSerializer):
    """
    Rider ko 'Available Deliveries' ki list mein dikhane ke liye.
    """
    store = StoreSerializer(source='order.store', read_only=True)
    customer_address = AddressSerializer(source='order.delivery_address', read_only=True)
    order_id = serializers.CharField(source='order.order_id', read_only=True)
    payment_method = serializers.SerializerMethodField()
    final_total = serializers.DecimalField(source='order.final_total', max_digits=10, decimal_places=2, read_only=True)
    
    distance_to_store = serializers.SerializerMethodField() 

    class Meta:
        model = Delivery
        fields = [
            'id',              
            'order_id',
            'status',
            'store',            
            'customer_address', 
            'payment_method',   
            'final_total',
            'distance_to_store',
            'estimated_delivery_time'
        ]
        read_only_fields = ['estimated_delivery_time']
    def get_payment_method(self, obj):
        """
        Safely order ka payment method nikalta hai.
        'obj' yahaan ek 'Delivery' instance hai.
        """
        payment = obj.order.payments.first()
        if payment:
            return payment.payment_method
        return None

    def get_distance_to_store(self, obj):
   
        if hasattr(obj, 'distance_to_store') and isinstance(obj.distance_to_store, Distance):
            return obj.distance_to_store.m 
        return None

class DeliveryDetailSerializer(serializers.ModelSerializer):
    """
    STEP 5.2: Customer ko OrderDetail mein dikhane ke liye
    ek naya simple delivery serializer.
    """
    class Meta:
        model = Delivery
        fields = [
            'status', 
            'estimated_delivery_time', 
            'accepted_at', 
            'at_store_at',
            'picked_up_at', 
            'delivered_at'
        ]

        
class StaffOrderStatusUpdateSerializer(serializers.Serializer):
    """
    Store staff se input lene ke liye (kya karna hai).
    """
    status = serializers.ChoiceField(
        choices=[
            Order.OrderStatus.PREPARING,
            Order.OrderStatus.READY_FOR_PICKUP
        ],
        required=True
    )