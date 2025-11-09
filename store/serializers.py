from rest_framework import serializers
from .models import Category, Store, Product, ProductVariant
from accounts.models import User
from .models import Review
from django.utils import timezone # <-- NAYA IMPORT

class CategorySerializer(serializers.ModelSerializer):
    """
    Category aur sub-category ko display karne ke liye serializer.
    (UPDATED: Ab nested 'children' ko support karta hai)
    """
    # children field, CategorySerializer ko hi recursively (baar-baar) call karega
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        # 'children' ko fields mein add karein
        fields = ['id', 'name', 'slug', 'icon', 'parent', 'children']
        read_only_fields = ['id', 'slug', 'parent', 'children']

    def get_children(self, obj):
        """
        Sirf active children ko recursively serialize karta hai.
        """
        # 'obj' yahaan parent category hai (e.g., "Fruits & Veg")
        # Hum uske active children (e.g., "Fresh Fruits") dhoondh rahe hain
        active_children = obj.children.filter(is_active=True)
        
        if active_children.exists():
            # Hum context pass karte hain (request ke liye, agar images hain)
            # Taki children ke icons ka URL bhi sahi bane
            serializer = CategorySerializer(active_children, many=True, context=self.context)
            return serializer.data
        
        return [] # Agar children nahi hain toh empty list

class StoreSerializer(serializers.ModelSerializer):
    """
    Store ki basic jaankari (naam, address) dikhane ke liye.
    """
    location = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id', 
            'name', 
            'address', 
            'location', 
            'opening_time', 
            'closing_time', 
            'is_active',
            'is_open'
        ]

    def get_location(self, obj):
        if obj.location:
            return {
                'latitude': obj.location.y,
                'longitude': obj.location.x
            }
        return None

    def get_is_open(self, obj) -> bool:
        """
        Check karta hai ki store abhi (current time) khula hai ya nahi.
        """
        if not obj.opening_time or not obj.closing_time:
            # Agar timing set nahi hai, toh hum assume karte hain ki woh hamesha khula hai
            return True 

        try:
            # Hum maante hain ki sabhi times server ke time (UTC) mein hain
            current_time = timezone.now().time()
            
            opening = obj.opening_time
            closing = obj.closing_time

            if opening < closing:
                # Standard case (e.g., 09:00 se 21:00)
                return opening <= current_time < closing
            else:
                # Overnight case (e.g., 21:00 se 05:00)
                # Ya toh current time opening time se zyada hai (raat 21:00 - 23:59)
                # Ya current time closing time se kam hai (subah 00:00 - 05:00)
                return current_time >= opening or current_time < closing
        
        except Exception:
            # Koi error aane par (jaise invalid time format), default True
            return True


class ProductSerializer(serializers.ModelSerializer):
    """
    Base Product ki jaankari (Sirf nested use ke liye).
    """
    category = CategorySerializer(read_only=True)
    class Meta:
        model = Product
        fields = [
            'id', 'name', 'description', 'brand', 'main_image', 'category',
            'average_rating', 'review_count' # <-- Naye fields add karein
        ]

# --- NAYA USER SERIALIZER (Sirf Review ke liye) ---
class ReviewUserSerializer(serializers.ModelSerializer):
    """Review ke andar user ka naam dikhane ke liye"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'profile_picture']

# --- NAYA REVIEW SERIALIZER ---
class ReviewSerializer(serializers.ModelSerializer):
    """
    Review ko list karne (GET) aur create karne (POST) ke liye.
    """
    user = ReviewUserSerializer(read_only=True)

    class Meta:
        model = Review
        fields = ['id', 'user', 'rating', 'comment', 'created_at']
        read_only_fields = ['id', 'user', 'created_at']
    
    def validate(self, data):
        # Check karein ki user ne pehle hi review toh nahi kar diya
        product_id = self.context['view'].kwargs.get('product_id')
        user = self.context['request'].user
        
        if Review.objects.filter(product_id=product_id, user=user).exists():
            raise serializers.ValidationError("You have already reviewed this product.")
            
        return data




class ProductVariantSerializer(serializers.ModelSerializer):
    """
    Product Variant ki jaankari (Sirf nested use ke liye).
    """
    product = ProductSerializer(read_only=True)
    image = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ['id', 'variant_name', 'sku', 'attributes', 'image', 'product']
    
    def get_image(self, obj):
        request = self.context.get('request')
        image_url = obj.get_image().url if obj.get_image() else None
        if request and image_url:
            return request.build_absolute_uri(image_url)
        return image_url