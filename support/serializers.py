from rest_framework import serializers
from .models import SupportTicket, TicketMessage
from orders.models import Order
from accounts.models import User

# Ek chhota serializer taaki message ke andar user ka naam dikha sakein
class TicketUserSerializer(serializers.ModelSerializer):
    """Sirf user ki zaroori info dikhane ke liye."""
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'is_staff']

class TicketMessageSerializer(serializers.ModelSerializer):
    """
    Ek single message ko dikhane ke liye.
    """
    user = TicketUserSerializer(read_only=True)
    
    class Meta:
        model = TicketMessage
        fields = ['id', 'user', 'message', 'created_at']

class SupportTicketListSerializer(serializers.ModelSerializer):
    """
    Ticket *list* ke liye halka serializer.
    """
    class Meta:
        model = SupportTicket
        fields = [
            'id', 
            'ticket_id',
            'subject', 
            'status', 
            'category',
            'updated_at',
        ]

class SupportTicketDetailSerializer(serializers.ModelSerializer):
    """
    Ek poore ticket (detail) ko dikhane ke liye.
    """
    user = TicketUserSerializer(read_only=True)
    # Nested messages
    messages = TicketMessageSerializer(many=True, read_only=True)
    order_id_str = serializers.CharField(source='order.order_id', read_only=True)
    
    class Meta:
        model = SupportTicket
        fields = [
            'id', 
            'ticket_id',
            'user', 
            'order_id_str', 
            'subject', 
            'category', 
            'status', 
            'created_at', 
            'updated_at',
            'messages' # Nested chat messages
        ]

class CreateTicketSerializer(serializers.ModelSerializer):
    """
    Customer se naya ticket create karne ke liye input lene ke liye.
    """
    # Hum order_id (string) lenge aur usse Order object banayenge
    order_id = serializers.CharField(
        required=False, 
        allow_null=True, 
        write_only=True,
        help_text="Is ticket se juda Order ID (e.g., 'ABC12345')"
    )
    
    # Pehla message jo customer likhega
    message = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = SupportTicket
        fields = ['subject', 'category', 'order_id', 'message']

    def validate_order_id(self, value):
        if not value:
            return None
        
        user = self.context['request'].user
        try:
            # Check karein ki order ID valid hai aur user ka hi hai
            order = Order.objects.get(order_id=value, user=user)
            return order # Hum poora Order object return karenge
        except Order.DoesNotExist:
            raise serializers.ValidationError("Aapke account par yeh order ID nahi mila.")

    def create(self, validated_data):
        user = self.context['request'].user
        first_message_text = validated_data.pop('message')
        
        # 'order_id' ko 'order' se replace karein (jo validation mein set hua)
        validated_data['order'] = validated_data.pop('order_id', None)
        
        # 1. Pehle ticket banayein
        ticket = SupportTicket.objects.create(
            user=user,
            status=SupportTicket.TicketStatus.OPEN,
            **validated_data
        )
        
        # 2. Us ticket ke liye pehla message banayein
        TicketMessage.objects.create(
            ticket=ticket,
            user=user,
            message=first_message_text,
            is_internal_note=False
        )
        
        return ticket

class AddMessageSerializer(serializers.ModelSerializer):
    """
    Ek maujooda ticket mein naya message add karne ke liye.
    """
    class Meta:
        model = TicketMessage
        fields = ['message']