from rest_framework import serializers
from django.utils import timezone
from accounts.models import User
from .models import Category, Store, Product, ProductVariant, Review, Banner

# YEH IMPORT AB SABSE AAKHRI CLASS (HomePageDataSerializer) KE LIYE HAI
# ISSE TOP PAR RAKHNA AB SAFE HAI KYUNKI HUMNE NEECHE CLASSES RE-ORDER KAR DI HAIN


class CategorySerializer(serializers.ModelSerializer):
    """
    Category aur sub-category ko display karne ke liye serializer.
    (UPDATED: Ab nested 'children' ko support karta hai)
    """
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'icon', 'parent', 'children']
        read_only_fields = ['id', 'slug', 'parent', 'children']

    def get_children(self, obj):
        active_children = obj.children.filter(is_active=True)
        if active_children.exists():
            serializer = CategorySerializer(active_children, many=True, context=self.context)
            return serializer.data
        return []

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
        if not obj.opening_time or not obj.closing_time:
            return True 
        try:
            current_time = timezone.localtime(timezone.now()).time()
            opening = obj.opening_time
            closing = obj.closing_time
            if opening < closing:
                return opening <= current_time < closing
            else:
                return current_time >= opening or current_time < closing
        except Exception:
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
            'average_rating', 'review_count'
        ]

# --- YEH CLASS UPAR MOVE HO GAYI HAI ---
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

# --- BAAKI CLASSES AB NEECHE HAIN ---

class ReviewUserSerializer(serializers.ModelSerializer):
    """Review ke andar user ka naam dikhane ke liye"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'profile_picture']

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
        product_id = self.context['view'].kwargs.get('product_id')
        user = self.context['request'].user
        
        if Review.objects.filter(product_id=product_id, user=user).exists():
            raise serializers.ValidationError("You have already reviewed this product.")
            
        return data

class BannerSerializer(serializers.ModelSerializer):
    """
    Promotional Banners ko serialize karne ke liye.
    """
    image = serializers.SerializerMethodField()

    class Meta:
        model = Banner
        fields = ['id', 'title', 'image', 'link']

    def get_image(self, obj):
        request = self.context.get('request')
        if obj.image and hasattr(obj.image, 'url'):
            return request.build_absolute_uri(obj.image.url)
        return None

class HomePageDataSerializer(serializers.Serializer):
    from inventory.serializers import StoreInventoryListSerializer 
    """
    Home Page API ke poore response ko structure karne ke liye.
    """
    banners = BannerSerializer(many=True, read_only=True)
    categories = CategorySerializer(many=True, read_only=True)
    featured_products = StoreInventoryListSerializer(many=True, read_only=True)