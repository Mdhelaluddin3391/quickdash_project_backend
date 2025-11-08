from rest_framework import serializers
from .models import Category, Store, Product, ProductVariant
from accounts.models import User
from .models import Review


class CategorySerializer(serializers.ModelSerializer):
    """
    Category aur sub-category ko display karne ke liye serializer.
    """
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'icon', 'parent']
        read_only_fields = ['id', 'slug', 'parent']


class StoreSerializer(serializers.ModelSerializer):
    """
    Store ki basic jaankari (naam, address) dikhane ke liye.
    """
    location = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id', 
            'name', 
            'address', 
            'location', 
            'opening_time', 
            'closing_time', 
            'is_active'
        ]

    def get_location(self, obj):
        if obj.location:
            return {
                'latitude': obj.location.y,
                'longitude': obj.location.x
            }
        return None


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