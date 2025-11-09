from rest_framework import serializers
from django.contrib.gis.geos import Point
from .models import RiderProfile, Delivery
from orders.models import Order
from accounts.serializers import AddressSerializer
from store.serializers import StoreSerializer
from django.contrib.gis.measure import Distance
# delivery/serializers.py
from .models import RiderProfile, Delivery, RiderEarning, RiderCashDeposit # <-- 'RiderCashDeposit' add karein
from .models import RiderProfile, Delivery, RiderEarning # <-- 'RiderEarning' yahaan add karein
from .models import RiderProfile, Delivery, RiderEarning, RiderCashDeposit, RiderApplication, RiderDocument
from rest_framework.exceptions import ValidationError



class RiderProfileUpdateSerializer(serializers.ModelSerializer):
    """
    Rider ko apni profile (online status, vehicle) update karne ke liye.
    """
    class Meta:
        model = RiderProfile
        fields = [
            'is_online', 
            'vehicle_details'
        ]

class RiderLocationUpdateSerializer(serializers.Serializer):
    """
    Rider se Latitude/Longitude input lene ke liye.
    """
    latitude = serializers.FloatField(required=True)
    longitude = serializers.FloatField(required=True)

    def update(self, instance, validated_data):
        instance.current_location = Point(
            validated_data['longitude'], 
            validated_data['latitude'], 
            srid=4326
        )
        instance.save()
        return instance

class RiderProfileDetailSerializer(serializers.ModelSerializer):
    """
    Rider ki poori profile dikhane ke liye.
    """
    username = serializers.CharField(source='user.username', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)
    
    current_location_coords = serializers.SerializerMethodField()

    class Meta:
        model = RiderProfile
        fields = [
            'username', 
            'phone_number', 
            'is_online', 
            'on_delivery',
            'vehicle_details',
            'rating',
            'current_location_coords'
        ]
        read_only_fields = ['username', 'phone_number', 'on_delivery', 'rating', 'current_location_coords']

    def get_current_location_coords(self, obj):
        if obj.current_location:
            return {'latitude': obj.current_location.y, 'longitude': obj.current_location.x}
        return None


class DeliveryUpdateSerializer(serializers.Serializer):
    """
    Rider se agla status lene ke liye.
    """
    status = serializers.ChoiceField(
        choices=[
            Delivery.DeliveryStatus.AT_STORE, 
            Delivery.DeliveryStatus.PICKED_UP, 
            Delivery.DeliveryStatus.DELIVERED
        ],
        required=True
    )

class RiderDeliverySerializer(serializers.ModelSerializer):
    """
    Rider ko 'Available Deliveries' ki list mein dikhane ke liye.
    """
    store = StoreSerializer(source='order.store', read_only=True)
    customer_address = AddressSerializer(source='order.delivery_address', read_only=True)
    order_id = serializers.CharField(source='order.order_id', read_only=True)
    payment_method = serializers.SerializerMethodField()
    final_total = serializers.DecimalField(source='order.final_total', max_digits=10, decimal_places=2, read_only=True)
    
    distance_to_store = serializers.SerializerMethodField() 

    class Meta:
        model = Delivery
        fields = [
            'id',              
            'order_id',
            'status',
            'store',            
            'customer_address', 
            'payment_method',   
            'final_total',
            'distance_to_store',
            'estimated_delivery_time'
        ]
        read_only_fields = ['estimated_delivery_time']
    def get_payment_method(self, obj):
        """
        Safely order ka payment method nikalta hai.
        'obj' yahaan ek 'Delivery' instance hai.
        """
        payment = obj.order.payments.first()
        if payment:
            return payment.payment_method
        return None

    def get_distance_to_store(self, obj):
   
        if hasattr(obj, 'distance_to_store') and isinstance(obj.distance_to_store, Distance):
            return obj.distance_to_store.m 
        return None

class DeliveryDetailSerializer(serializers.ModelSerializer):
    """
    STEP 5.2: Customer ko OrderDetail mein dikhane ke liye
    ek naya simple delivery serializer.
    """
    class Meta:
        model = Delivery
        fields = [
            'status', 
            'estimated_delivery_time', 
            'accepted_at', 
            'at_store_at',
            'picked_up_at', 
            'delivered_at'
        ]

        
class StaffOrderStatusUpdateSerializer(serializers.Serializer):
    """
    Store staff se input lene ke liye (kya karna hai).
    """
    status = serializers.ChoiceField(
        choices=[
            Order.OrderStatus.PREPARING,
            Order.OrderStatus.READY_FOR_PICKUP
        ],
        required=True
    )

class RiderEarningSerializer(serializers.ModelSerializer):
    """
    Rider ko uski kamai ki details dikhane ke liye.
    """
    class Meta:
        model = RiderEarning
        fields = [
            'order_id_str',
            'base_fee',
            'tip',
            'total_earning',
            'status',
            'created_at'
        ]



class RiderCashDepositSerializer(serializers.ModelSerializer):
    """
    Rider ko cash deposit request create karne (POST) aur
    apni history dekhne (GET) ke liye.
    """
    
    # Read-only fields jo GET request mein dikhenge
    rider_name = serializers.CharField(source='rider.user.username', read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = RiderCashDeposit
        fields = [
            'id',
            'rider_name',     # Read-only
            'amount',         # Writable
            'payment_method', # Writable
            'transaction_id', # Writable
            'notes',          # Writable
            'status',         # Read-only
            'admin_notes',    # Read-only (Admin notes dekhne ke liye)
            'created_at',     # Read-only
        ]
        
        # Yeh fields POST request mein read-only honge
        read_only_fields = ['id', 'rider_name', 'status', 'admin_notes', 'created_at']

    def validate_amount(self, value):
        """
        Check karein ki amount 0 se zyada ho aur rider ke
        paas jitna cash hai, usse zyada na ho.
        """
        if value <= Decimal('0.00'):
            raise serializers.ValidationError("Amount 0 se zyada hona chahiye.")
        
        rider = self.context['request'].user.rider_profile
        if value > rider.cash_on_hand:
            raise serializers.ValidationError(
                f"Aap {value} deposit nahi kar sakte. "
                f"Aapke paas sirf ₹{rider.cash_on_hand} cash hai."
            )
        return value

    def validate_transaction_id(self, value):
        """
        Check karein ki UPI/Bank transfer ke liye Transaction ID zaroori hai.
        """
        # 'payment_method' ko initial_data se fetch karein (kyunki validate() mein nahi milta)
        payment_method = self.initial_data.get('payment_method')
        
        if payment_method in [
            RiderCashDeposit.DepositPaymentMethod.UPI, 
            RiderCashDeposit.DepositPaymentMethod.BANK_TRANSFER
        ] and not value:
            raise serializers.ValidationError("UPI/Bank Transfer ke liye Transaction ID zaroori hai.")
            
        return value
    
class RiderDocumentSerializer(serializers.ModelSerializer):
    """
    Rider ke upload kiye gaye document ko dikhane ke liye.
    """
    document_file_url = serializers.FileField(source='document_file', read_only=True)
    
    class Meta:
        model = RiderDocument
        fields = [
            'id',
            'document_type',
            'document_file_url',
            'is_verified' # Admin verify karega
        ]
        read_only_fields = ['is_verified']

class RiderApplicationSerializer(serializers.ModelSerializer):
    """
    Rider ki application ka status dikhane ke liye (Read-only).
    """
    # Nested documents
    documents = RiderDocumentSerializer(many=True, read_only=True)
    
    class Meta:
        model = RiderApplication
        fields = [
            'id',
            'status',
            'vehicle_details',
            'admin_notes', # Admin ne reject kiya toh note dikhega
            'documents',   # Uploaded documents ki list
            'created_at',
            'updated_at'
        ]
        read_only_fields = fields # Yeh poora serializer read-only hai

class RiderApplicationCreateSerializer(serializers.ModelSerializer):
    """
    Rider se application create karne ke liye input lene ke liye.
    """
    class Meta:
        model = RiderApplication
        fields = ['vehicle_details'] # User sirf vehicle details daalega

    def validate(self, data):
        user = self.context['request'].user
        
        # Check karein ki user pehle se hi rider toh nahi hai
        if hasattr(user, 'rider_profile'):
            raise ValidationError("Aap pehle se hi ek registered rider hain.")
            
        # Check karein ki user ne pehle se apply toh nahi kiya
        if RiderApplication.objects.filter(user=user).exists():
            raise ValidationError("Aap pehle hi application submit kar chuke hain.")
            
        return data

class RiderDocumentUploadSerializer(serializers.ModelSerializer):
    """
    Rider se document upload karwane ke liye (Input).
    """
    class Meta:
        model = RiderDocument
        fields = [
            'document_type', 
            'document_file' # Yeh file upload field hai
        ]

    def validate(self, data):
        user = self.context['request'].user
        
        # 1. Application dhoondein
        try:
            application = RiderApplication.objects.get(user=user)
        except RiderApplication.DoesNotExist:
            raise ValidationError("Aapne abhi tak application create nahi ki hai.")
            
        # 2. Status check karein
        if application.status != RiderApplication.ApplicationStatus.PENDING:
            raise ValidationError(f"Aapki application '{application.status}' hai. Aap ab documents upload nahi kar sakte.")
            
        # 3. Check karein ki yeh document pehle se upload toh nahi
        doc_type = data.get('document_type')
        if RiderDocument.objects.filter(application=application, document_type=doc_type).exists():
            raise ValidationError(f"Aap pehle hi '{doc_type}' upload kar chuke hain.")
            
        # View mein istemaal ke liye application ko context mein save karein
        self.context['application'] = application
        return data
        
    def create(self, validated_data):
        # View se 'application' object lein
        application = self.context['application']
        
        # Naya document banayein
        document = RiderDocument.objects.create(
            application=application,
            document_type=validated_data.get('document_type'),
            document_file=validated_data.get('document_file')
        )
        return document