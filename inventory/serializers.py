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
class StaffInventoryUpdateSerializer(serializers.ModelSerializer):
    """
    Staff ko inventory item (price, stock) update karne ke liye serializer.
    """
    
    # Variant ki thodi jaankari dikhane ke liye (read-only)
    variant_name = serializers.CharField(source='variant.variant_name', read_only=True)
    product_name = serializers.CharField(source='variant.product.name', read_only=True)

    class Meta:
        model = StoreInventory
        fields = [
            'id',
            'product_name',     # Read-only
            'variant_name',     # Read-only
            'price',            # Writable (likh sakte hain)
            'sale_price',       # Writable
            'stock_quantity',   # Writable
            'is_available',     # Writable
        ]
        
        # Yeh fields sirf read kiye ja sakte hain, update nahi honge
        read_only_fields = ['id', 'product_name', 'variant_name']

    def validate(self, data):
        """
        Custom validation, jaise sale price price se zyada na ho.
        """
        # instance=self.instance check karta hai ki yeh PATCH request hai ya nahi
        # taaki hum puraane 'price' ko naye 'sale_price' se compare kar sakein
        
        price = data.get('price', getattr(self.instance, 'price', None))
        sale_price = data.get('sale_price', getattr(self.instance, 'sale_price', None))

        if sale_price is not None and price is not None and sale_price > price:
            raise serializers.ValidationError({
                "sale_price": "Sale price regular price se zyada nahi ho sakta."
            })
            
        if data.get('stock_quantity', 0) < 0:
             raise serializers.ValidationError({
                "stock_quantity": "Stock 0 se kam nahi ho sakta."
            })

        return data

        
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