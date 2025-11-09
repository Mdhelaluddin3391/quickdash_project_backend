# File: dashboard/serializers.py (Cleaned Version)

from rest_framework import serializers
from inventory.models import StoreInventory
from orders.models import Order
from accounts.models import CustomerProfile, Address, User

# Doosre apps se Serializers ko reuse karein
from inventory.serializers import ProductVariantSerializer
from accounts.serializers import CustomerProfileSerializer, AddressSerializer


class DashboardLowStockItemSerializer(serializers.ModelSerializer):
    """
    Dashboard par "Low Stock" items dikhane ke liye halka serializer.
    """
    variant = ProductVariantSerializer(read_only=True)
    
    class Meta:
        model = StoreInventory
        fields = [
            'id',
            'variant',
            'stock_quantity'
        ]

class StaffDashboardSerializer(serializers.Serializer):
    """
    Store Staff Dashboard ke poore data ko structure karne ke liye.
    (Yeh ek Read-only serializer hai)
    """
    today_sales = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    today_orders_count = serializers.IntegerField(read_only=True)
    pending_pick_tasks = serializers.IntegerField(read_only=True)
    preparing_orders_count = serializers.IntegerField(read_only=True)
    ready_for_pickup_orders_count = serializers.IntegerField(read_only=True)
    low_stock_items = DashboardLowStockItemSerializer(many=True, read_only=True)


class ManagerOrderListSerializer(serializers.ModelSerializer):
    """
    Manager ko order list dikhane ke liye halka serializer.
    """
    customer_name = serializers.CharField(source='user.get_full_name', read_only=True)
    customer_phone = serializers.CharField(source='user.phone_number', read_only=True)

    class Meta:
        model = Order
        fields = [
            'order_id',
            'status',
            'payment_status',
            'final_total',
            'created_at',
            'customer_name',
            'customer_phone'
        ]

class CancelOrderItemSerializer(serializers.Serializer):
    """
    Input ke liye: Jab manager ek order item ko FC (Fulfilment Cancel) karta hai.
    """
    order_item_id = serializers.IntegerField(
        required=True,
        help_text="Us OrderItem ki ID jise cancel karna hai"
    )
    quantity_to_cancel = serializers.IntegerField(
        required=True,
        min_value=1,
        help_text="Kitni quantity cancel karni hai (e.g., 1, 2)"
    )


class ManagerCustomerDetailSerializer(serializers.ModelSerializer):
    """
    Manager ko customer ki poori detail dikhane ke liye.
    """
    profile = CustomerProfileSerializer(source='customer_profile', read_only=True)
    addresses = AddressSerializer(many=True, read_only=True)

    class Meta:
        model = User # Hum 'User' model se shuru kar rahe hain
        fields = [
            'id',
            'phone_number',
            'profile', # Nested profile data
            'addresses'  # Nested list of addresses
        ]