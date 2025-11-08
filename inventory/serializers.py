from rest_framework import serializers
from .models import StoreInventory
from store.serializers import ProductVariantSerializer, StoreSerializer

class StoreInventorySerializer(serializers.ModelSerializer):
    """
    Yeh hamara main "Product" Serializer hai jo customer ko dikhega.
    Yeh variant, price, aur stock sab dikhata hai.
    """
    variant = ProductVariantSerializer(read_only=True)
    
    store = StoreSerializer(read_only=True)
    
    current_price = serializers.DecimalField(
        source='get_current_price', 
        max_digits=10, 
        decimal_places=2, 
        read_only=True
    )
    is_on_sale = serializers.BooleanField(read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = StoreInventory
        fields = [
            'id',               
            'variant',          
            'store',          
            'price',          
            'sale_price',      
            'current_price',    
            'stock_quantity',
            'is_on_sale',
            'is_in_stock',
            'is_available',
        ]

class StoreInventoryListSerializer(StoreInventorySerializer):
    """
    Product List view ke liye halka (lightweight) serializer.
    Ismein 'store' ki detail nahi bhejenge kyunki user pehle hi 
    store select kar chuka hai.
    """
    class Meta(StoreInventorySerializer.Meta):
        fields = [
            'id', 
            'variant', 
            'price', 
            'sale_price', 
            'current_price', 
            'stock_quantity',
            'is_on_sale',
            'is_in_stock',
            'is_available',
        ]