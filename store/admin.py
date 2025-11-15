# store/admin.py
from django.contrib import admin
# GIS models ke liye 'admin.GISModelAdmin' ka istemaal karein
from django.contrib.gis import admin as gis_admin
from .models import Category, Store, Product, ProductVariant, Review, Banner

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """
    Product Categories ke liye Admin.
    """
    list_display = ('name', 'parent', 'slug', 'is_active')
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'slug')
    # 'name' likhte hi 'slug' automatically fill ho jayega
    prepopulated_fields = {'slug': ('name',)} 
    autocomplete_fields = ('parent',)

@admin.register(Store)
class StoreAdmin(gis_admin.GISModelAdmin):
    """
    Dark Stores ke liye Admin (GIS enabled).
    """
    list_display = ('name', 'address', 'is_active', 'opening_time', 'closing_time')
    list_filter = ('is_active',)
    search_fields = ('name', 'address')

# --- Product ke andar Inlines ---

class ProductVariantInline(admin.TabularInline):
    """
    'Product' admin page ke andar 'Variants' ko manage karne ke liye.
    """
    model = ProductVariant
    extra = 1 # Naya add karne ke liye 1 extra row
    fields = ('variant_name', 'sku', 'image', 'attributes')

class ReviewInline(admin.TabularInline):
    """
    'Product' admin page ke andar 'Reviews' dekhne ke liye.
    """
    model = Review
    extra = 0 # Naye review admin se add nahi karne
    fields = ('user', 'rating', 'comment', 'created_at')
    readonly_fields = ('user', 'rating', 'comment', 'created_at')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Main Product ke liye Admin.
    """
    list_display = (
        'name', 
        'category', 
        'brand', 
        'is_active', 
        'average_rating', 
        'review_count'
    )
    list_filter = ('category', 'brand', 'is_active')
    search_fields = ('name', 'brand')
    readonly_fields = ('average_rating', 'review_count', 'created_at', 'updated_at')
    autocomplete_fields = ('category',)
    
    # Inlines ko yahaan register karein
    inlines = [ProductVariantInline, ReviewInline]

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """
    Sabhi Reviews ko alag se manage karne ke liye.
    """
    list_display = ('product', 'user', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('product__name', 'user__username')
    readonly_fields = ('product', 'user', 'rating', 'comment')

@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    """
    Promotional Banners ke liye Admin.
    """
    list_display = ('title', 'order', 'is_active', 'link')
    list_filter = ('is_active',)
    search_fields = ('title',)
    list_editable = ('order', 'is_active')