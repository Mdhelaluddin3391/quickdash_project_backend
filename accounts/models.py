from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.gis.db import models as gis_models
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction



class User(AbstractUser):
    """
    Custom User Model.
    """
    
    
    email = models.EmailField(blank=True, null=True)
    
    phone_number = models.CharField(
        max_length=15, 
        unique=True, 
        null=True, 
        blank=True, 
        db_index=True,
        help_text="Login ke liye istemaal hoga (e.g., +919876543210)"
    )
    
    profile_picture = models.ImageField(
        upload_to='profile_pics/', 
        null=True, 
        blank=True,
        verbose_name="Profile Picture"
    )
    fcm_token = models.CharField(
        max_length=255, 
        null=True, 
        blank=True,
        db_index=True,
        help_text="Firebase Cloud Messaging token for push notifications"
    )
    
    REQUIRED_FIELDS = ['first_name', 'last_name', 'email'] 

    def __str__(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name} ({self.phone_number})"
        return self.phone_number or self.username



class CustomerProfile(models.Model):
    """
    Har user ke paas yeh profile hogi (by default).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='customer_profile'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Customer Profile for {self.user.username}"

class StoreStaffProfile(models.Model):
    """
    Yeh profile user ko 'Store Staff' banati hai.
    Ise Admin Panel se manually add kiya jayega.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='store_staff_profile'
    )
    store = models.ForeignKey(
        'store.Store', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='staff_members'
    )
    is_manager = models.BooleanField(
        default=False,
        help_text="Kya yeh staff member is store ka manager hai?"
    )
    
    def __str__(self):
        if self.store:
            return f"Staff {self.user.username} at {self.store.name}"
        return f"Staff {self.user.username} (Unassigned)"


class Address(gis_models.Model):

    class AddressType(models.TextChoices):
        HOME = 'HOME', 'Home'
        WORK = 'WORK', 'Work'
        OTHER = 'OTHER', 'Other'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='addresses'
    )
    address_type = models.CharField(
        max_length=10, 
        choices=AddressType.choices, 
        default=AddressType.HOME
    )
    full_address = models.TextField(help_text="Poora address (House No, Street, etc.)")
    landmark = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10, db_index=True)
    
    location = gis_models.PointField(
        srid=4326, 
        null=True, 
        blank=True,
        help_text="User ki exact location (Longitude, Latitude)"
    )
    
    is_default = models.BooleanField(
        default=False,
        help_text="Kya yeh user ka primary address hai?"
    )

    def __str__(self):
        return f"{self.get_address_type_display()} Address for {self.user.username}"

    def save(self, *args, **kwargs):
        if self.is_default:
            with transaction.atomic():
                Address.objects.filter(user=self.user, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super(Address, self).save(*args, **kwargs)

    class Meta:
        verbose_name_plural = "Addresses"




@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Yeh signal User ke bante hi trigger hota hai.
    Yeh har naye user ke liye default 'CustomerProfile' banata hai.
    
    RiderProfile aur StoreStaffProfile ab yahaan nahi banenge.
    Woh manually Admin Panel se ya "Apply" API se banenge.
    """
    
    if created:
        try:
           
            CustomerProfile.objects.create(user=instance)
            
        except Exception as e:
            print(f"Error creating default customer profile for user {instance.username}: {e}")