from django.db import models
from django.contrib.gis.db import models as gis_models
from django.utils.text import slugify
from django.conf import settings # <-- Naya import
from django.db.models import Avg # <-- Naya import

class TimestampedModel(models.Model):
    """
    Ek abstract model jo har model mein created_at aur updated_at 
    fields automatically add kar dega.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


class Category(TimestampedModel):
    """
    Products ki categories, sub-categories ke support ke saath.
    Jaise: Dairy -> Milk -> Toned Milk
    """
    parent = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='children',
        help_text="Is category ka parent (agar yeh ek sub-category hai)"
    )
    name = models.CharField(
        max_length=150, 
        db_index=True,
        help_text="Category ka naam (e.g., 'Dairy & Breakfast')"
    )
    slug = models.SlugField(
        max_length=150, 
        unique=True, 
        db_index=True,
        help_text="URL ke liye unique slug (e.g., 'dairy-breakfast')"
    )
    icon = models.ImageField(
        upload_to='category_icons/', 
        null=True, 
        blank=True,
        help_text="Category ke liye ek chhota icon"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Kya yeh category site par visible hai?"
    )

    class Meta:
        verbose_name_plural = "Categories"
        unique_together = ('slug', 'parent')

    def __str__(self):
        full_path = [self.name]
        k = self.parent
        while k is not None:
            full_path.append(k.name)
            k = k.parent
        return ' > '.join(full_path[::-1])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super(Category, self).save(*args, **kwargs)


class Store(TimestampedModel):
    """
    Hamare "Dark Stores" ya warehouses.
    Yahaan GeoDjango ka istemaal kiya gaya hai.
    """
    name = models.CharField(
        max_length=100, 
        help_text="Dark store ka naam (e.g., 'Koramangala Hub')"
    )
    address = models.TextField(
        help_text="Store ka poora address"
    )
    location = gis_models.PointField(
        srid=4326, 
        null=True, 
        blank=True,
        help_text="Store ki exact location (Longitude, Latitude)"
    )
    opening_time = models.TimeField(null=True, blank=True)
    closing_time = models.TimeField(null=True, blank=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Kya yeh store operations ke liye active hai?"
    )

    def __str__(self):
        return self.name


class Product(TimestampedModel):
    """
    Base Product. Yeh "concept" hai, jaise 'Amul Taaza Milk'.
    Asal mein bikne wala item 'ProductVariant' hota hai.
    """
    category = models.ForeignKey(
        Category, 
        on_delete=models.PROTECT, 
        related_name='products',
        help_text="Yeh product kis category mein aata hai"
    )
    name = models.CharField(
        max_length=255, 
        db_index=True,
        help_text="Product ka naam (e.g., 'Amul Taaza Milk')"
    )
    description = models.TextField(
        blank=True,
        help_text="Product ke baare mein detail jaankari"
    )
    brand = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        db_index=True
    )
    main_image = models.ImageField(
        upload_to='product_images/',
        help_text="Product ki primary image"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Kya yeh product line active hai?"
    )

    average_rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        default=0.00,
        help_text="Sabhi reviews ki average rating"
    )
    review_count = models.PositiveIntegerField(
        default=0,
        help_text="Kitne logo ne review diya hai"
    )
    # --- END NAYE FIELDS ---
    def __str__(self):
        return self.name


class ProductVariant(TimestampedModel):
    """
    Yeh woh item hai jo असल mein bikta hai aur inventory mein track hota hai.
    e.g., 'Amul Taaza Milk' (Product) -> '500ml Pouch' (Variant)
    e.g., 'Amul Taaza Milk' (Product) -> '1L TetraPak' (Variant)
    """
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='variants',
        help_text="Yeh variant kis base product ka hai"
    )
    variant_name = models.CharField(
        max_length=255, 
        help_text="Variant ka naam (e.g., '500ml Pouch', '1kg Packet', 'Red')"
    )
    sku = models.CharField(
        max_length=100, 
        unique=True, 
        db_index=True,
        help_text="Stock Keeping Unit - har variant ke liye unique"
    )
    image = models.ImageField(
        upload_to='variant_images/', 
        null=True, 
        blank=True,
        help_text="Agar is variant ki image alag hai toh yahaan daalein"
    )
    attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON format mein attributes (e.g., size, color, weight)"
    )

    def __str__(self):
        return f"{self.product.name} ({self.variant_name})"

    def get_image(self):
        return self.image or self.product.main_image



class Review(TimestampedModel):
    """
    Product ke liye customer reviews aur ratings.
    """
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='reviews',
        help_text="Kis product ke liye review hai"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reviews',
        help_text="Kis user ne review diya"
    )
    rating = models.PositiveIntegerField(
        choices=[(1, '1'), (2, '2'), (3, '3'), (4, '4'), (5, '5')],
        help_text="Rating (1 se 5 star)"
    )
    comment = models.TextField(
        blank=True,
        help_text="Customer ka text review"
    )

    class Meta:
        ordering = ['-created_at']
        # Ek user ek product par ek hi review de sakta hai
        unique_together = ('product', 'user')

    def __str__(self):
        return f"Review for {self.product.name} by {self.user.username} ({self.rating} stars)"
        
    def save(self, *args, **kwargs):
        """
        Jab review save ho, toh Product ki average rating update karo.
        """
        super().save(*args, **kwargs) # Pehle review save karein
        
        # Ab Product par rating update karein
        try:
            # product object par lock lagayein
            product = Product.objects.select_for_update().get(id=self.product.id)
            
            # Nayi average rating calculate karein
            agg = product.reviews.aggregate(
                avg_rating=Avg('rating'),
                count=models.Count('id')
            )
            
            product.average_rating = agg.get('avg_rating') or 0.00
            product.review_count = agg.get('count') or 0
            product.save(update_fields=['average_rating', 'review_count'])
            
        except Product.DoesNotExist:
            pass # Product shayad delete ho gaya ho