# wms/serializers.py
from rest_framework import serializers
from .models import Location, WmsStock, PickTask
from inventory.models import StoreInventory
from store.serializers import ProductVariantSerializer

class LocationSerializer(serializers.ModelSerializer):
    """
    Warehouse locations (e.g., RACK-A) ko list karne ke liye.
    """
    class Meta:
        model = Location
        fields = ['id', 'code', 'store']


class WmsStockReceiveSerializer(serializers.Serializer):
    """
    Serializer for "Workflow A: Receive Stock" API
    Yeh input lega: Kaun sa item, Kis location par, Kitni quantity.
    """
    inventory_summary_id = serializers.IntegerField(required=True)
    location_id = serializers.IntegerField(required=True)
    quantity = serializers.IntegerField(required=True, min_value=1)

    def validate_inventory_summary_id(self, value):
        """
        Check karein ki StoreInventory item staff ke hi store ka hai.
        """
        user = self.context['request'].user
        store = user.store_staff_profile.store

        if not StoreInventory.objects.filter(id=value, store=store).exists():
            raise serializers.ValidationError("Inventory item not found at your store.")
        return value

    def validate_location_id(self, value):
        """
        Check karein ki Location staff ke hi store ki hai.
        """
        user = self.context['request'].user
        store = user.store_staff_profile.store

        if not Location.objects.filter(id=value, store=store).exists():
            raise serializers.ValidationError("Location not found at your store.")
        return value

    def create(self, validated_data):
        """
        Stock ko create ya update karein.
        """
        inv_summary_id = validated_data['inventory_summary_id']
        loc_id = validated_data['location_id']
        qty_to_add = validated_data['quantity']

        # get_or_create WmsStock entry
        stock_item, created = WmsStock.objects.get_or_create(
            inventory_summary_id=inv_summary_id,
            location_id=loc_id,
            defaults={'quantity': 0}
        )

        # Quantity add karein (overwrite nahi)
        stock_item.quantity += qty_to_add
        stock_item.save()

        # Note: Signal (models.py mein) automatically 
        # StoreInventory.stock_quantity ko update kar dega.

        return stock_item


class PickTaskLocationSerializer(serializers.ModelSerializer):
    """PickTask ke andar location dikhane ke liye halka serializer"""
    class Meta:
        model = Location
        fields = ['code']

class PickTaskSerializer(serializers.ModelSerializer):
    """
    Serializer for "Workflow B: Picker Mobile App"
    Picker ko uske tasks dikhane ke liye.
    """
    variant = ProductVariantSerializer(read_only=True)
    location = PickTaskLocationSerializer(read_only=True)
    order_id_str = serializers.CharField(source='order.order_id', read_only=True)

    class Meta:
        model = PickTask
        fields = [
            'id',
            'order_id_str',
            'location',
            'variant',
            'quantity_to_pick',
            'status',
            'created_at'
        ]