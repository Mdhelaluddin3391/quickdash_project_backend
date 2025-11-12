from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Address, CustomerProfile
from django.contrib.gis.geos import Point
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password # <-- Naya import
from django.core.exceptions import ValidationError


User = get_user_model()

class OTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)

class OTPVerifySerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6)

class StaffLoginSerializer(serializers.Serializer):
    """
    (UPDATED)
    Sirf Store Staff (Manager/Picker) ke (Phone + Password) Login ke liye.
    Riders ab iska istemaal nahi kar sakte.
    """
    phone_number = serializers.CharField(max_length=15, write_only=True)
    password = serializers.CharField(
        style={'input_type': 'password'},
        trim_whitespace=False,
        write_only=True
    )

    def validate(self, data):
        phone_number = data.get('phone_number')
        password = data.get('password')

        if not phone_number or not password:
            raise serializers.ValidationError("Phone number aur password dono zaroori hain.", code='authorization')

        user = authenticate(request=self.context.get('request'), username=phone_number, password=password)

        if not user:
            raise serializers.ValidationError("Invalid credentials. Sahi phone number ya password daalein.", code='authorization')

        # --- YEH BADLAAV HAI ---
        # Ab hum sirf 'store_staff_profile' check karenge
        if not hasattr(user, 'store_staff_profile'):
            raise serializers.ValidationError("Aap is portal ke liye authorized nahi hain. Yeh login sirf store staff ke liye hai.", code='authorization')
        # --- BADLAAV KHATAM ---
        
        data['user'] = user
        return data


class AddressSerializer(serializers.ModelSerializer):
    """
    Customer ke Address ko create/list/update karne ke liye serializer.
    """
    location = serializers.SerializerMethodField(read_only=True)
    latitude = serializers.FloatField(write_only=True, required=False)
    longitude = serializers.FloatField(write_only=True, required=False)


    class Meta:
        model = Address
        fields = [
            'id', 
            'user', 
            'full_address', 
            'city', 
            'pincode', 
            'address_type', 
            'location', 
            'is_default',
            'latitude', 
            'longitude' 
        ]
        read_only_fields = ['user'] 

    def get_location(self, obj):
        if obj.location:
            return {'latitude': obj.location.y, 'longitude': obj.location.x}
        return None

    def create(self, validated_data):
        latitude = validated_data.pop('latitude', None)
        longitude = validated_data.pop('longitude', None)
        

        location_point = None
        

        if latitude is not None and longitude is not None:
            location_point = Point(longitude, latitude, srid=4326) 
        
 
        validated_data['location'] = location_point
        

        return super().create(validated_data)


    def update(self, instance, validated_data):

        latitude = validated_data.pop('latitude', None)
        longitude = validated_data.pop('longitude', None)
        
        if latitude is not None and longitude is not None:
            instance.location = Point(longitude, latitude, srid=4326)
        

        return super().update(instance, validated_data)



class CustomerProfileSerializer(serializers.ModelSerializer):

    first_name = serializers.CharField(source='user.first_name', required=False)
    last_name = serializers.CharField(source='user.last_name', required=False)
    email = serializers.EmailField(source='user.email', required=False)

    class Meta:
        model = CustomerProfile
        fields = ['id', 'user', 'first_name', 'last_name', 'email']
        read_only_fields = ['user']

    def update(self, instance, validated_data):
        """
        Nested user data ko update karne ke liye
        """

        user_data = validated_data.pop('user', {}) 
        user = instance.user 


        user.first_name = user_data.get('first_name', user.first_name)
        user.last_name = user_data.get('last_name', user.last_name)
        user.email = user_data.get('email', user.email)
        user.save()
        

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance


class FCMTokenSerializer(serializers.Serializer):
    """
    Mobile app se FCM token lene ke liye.
    """
    fcm_token = serializers.CharField(max_length=255, required=True)

    def validate_fcm_token(self, value):
        if not value:
            raise serializers.ValidationError("FCM token cannot be empty.")
        return value


class StaffPasswordResetRequestSerializer(serializers.Serializer):
    """
    (UPDATED)
    Step 1: Sirf Staff ke phone number par password reset OTP bhejta hai.
    """
    phone_number = serializers.CharField(max_length=15)

    def validate_phone_number(self, value):
        try:
            user = User.objects.get(phone_number=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Is phone number se koi staff account register nahi hai.")
        
        # --- YEH BADLAAV HAI ---
        # Ab hum sirf 'store_staff_profile' check karenge
        if not hasattr(user, 'store_staff_profile'):
             raise serializers.ValidationError("Yeh account staff account nahi hai.")
        # --- BADLAAV KHATAM ---
             
        return value

class StaffPasswordResetConfirmSerializer(serializers.Serializer):
    """
    Step 2: Phone number, OTP, aur naya password lene ke liye.
    """
    phone_number = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6)
    new_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'},
        validators=[validate_password] # Django ke built-in password validators
    )
    confirm_password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Dono password match nahi karte."})
        return data
    

class StaffGoogleLoginSerializer(serializers.Serializer):
    """
    Staff Google Login ke liye frontend se 'id_token' lene ke liye.
    """
    id_token = serializers.CharField(
        write_only=True,
        required=True,
        help_text="Frontend se mila Google ID Token"
    )