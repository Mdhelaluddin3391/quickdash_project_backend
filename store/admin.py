from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin 
from .models import Category, Store, Product, ProductVariant
from .models import Category, Store, Product, ProductVariant, Banner





@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'is_active', 'link')
    list_editable = ('order', 'is_active')
    search_fields = ('title',)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'slug', 'is_active')
    list_filter = ('is_active', 'parent')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Store)
class StoreAdmin(GISModelAdmin):
    list_display = ('name', 'address', 'is_active')
    search_fields = ('name', 'address')
    list_filter = ('is_active',)


class ProductVariantInline(admin.TabularInline):
    """
    Yeh 'Product' page ke andar 'Variants' add karne ka form dega.
    """
    model = ProductVariant
    extra = 1 
    fields = ('variant_name', 'sku', 'image', 'attributes')

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'brand', 'is_active')
    list_filter = ('is_active', 'category', 'brand')
    search_fields = ('name', 'brand', 'category__name')
    inlines = [ProductVariantInline]

@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    """
    Variants ko alag se manage karne ke liye (optional)
    """
    list_display = ('product', 'variant_name', 'sku')
    search_fields = ('sku', 'product__name', 'variant_name')
    list_filter = ('product__category',)