from rest_framework import serializers
from .models import Cart, CartItem
from inventory.models import StoreInventory
from inventory.serializers import StoreInventoryListSerializer 
from store.serializers import StoreSerializer 

class CartItemAddSerializer(serializers.Serializer):
    """
    Input validation ke liye: Jab item cart mein add karein.
    """
    inventory_item_id = serializers.IntegerField(
        help_text="StoreInventory item ki ID"
    )
    quantity = serializers.IntegerField(
        min_value=1,
        default=1,
        help_text="Kitni quantity add karni hai"
    )

    def validate_inventory_item_id(self, value):
        """
        Check karein ki yeh inventory item ID maujood hai aur available hai.
        """
        if not StoreInventory.objects.filter(id=value, is_available=True, stock_quantity__gt=0).exists():
            raise serializers.ValidationError("Product not found or is out of stock.")
        return value


class CartItemUpdateSerializer(serializers.Serializer):
    """
    Input validation ke liye: Jab item ki quantity update karein.
    """
    quantity = serializers.IntegerField(
        min_value=0, 
        help_text="Nayi quantity (0 set karne par item delete ho jayega)"
    )


class CartItemSerializer(serializers.ModelSerializer):
    """
    Ek single cart item ko poori detail ke saath dikhata hai.
    """
    inventory_item = StoreInventoryListSerializer(read_only=True)
    item_total_price = serializers.FloatField(read_only=True)

    class Meta:
        model = CartItem
        fields = [
            'id',              
            'inventory_item',   
            'quantity',
            'item_total_price' 
        ]


class CartSerializer(serializers.ModelSerializer):
    """
    User ke poore cart ko dikhata hai.
    """
    items = CartItemSerializer(many=True, read_only=True)
    
    store = StoreSerializer(read_only=True) 
    
    total_price = serializers.FloatField(read_only=True)
    item_count = serializers.IntegerField(read_only=True)
    total_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = Cart
        fields = [
            'id',
            'user',
            'store',            
            'items',            
            'item_count',       
            'total_quantity',  
            'total_price',     
            'updated_at'
        ]
        read_only_fields = ['id', 'user', 'store', 'items', 'total_price', 'item_count', 'total_quantity', 'updated_at']