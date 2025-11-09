from django.shortcuts import render

# Create your views here.
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import SupportTicket, TicketMessage
from .serializers import (
    SupportTicketListSerializer,
    SupportTicketDetailSerializer, 
    CreateTicketSerializer, 
    AddMessageSerializer,
    TicketMessageSerializer
)
from accounts.permissions import IsCustomer
from django.db.models import Q # Non-internal messages filter karne ke liye
from django.db.models import Prefetch

class SupportTicketListCreateView(generics.ListCreateAPIView):
    """
    API: GET, POST /api/support/tickets/
    GET: Customer ke saare support tickets list karta hai.
    POST: Customer ke liye ek naya support ticket create karta hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return CreateTicketSerializer
        return SupportTicketListSerializer # List ke liye halka serializer

    def get_queryset(self):
        # Sirf user ke apne tickets dikhayein
        return SupportTicket.objects.filter(
            user=self.request.user
        ).order_by('-updated_at')

    def perform_create(self, serializer):
        # Serializer ka 'create' method call karein, jo ticket aur pehla message banayega
        ticket = serializer.save()
        
        # Note: Response mein hum poora detail serializer bhej sakte hain
        # taaki user ko turant poora ticket dikhe
        # (Lekin abhi ke liye, default 201 Created response kaafi hai)

class SupportTicketDetailView(generics.RetrieveAPIView):
    """
    API: GET /api/support/tickets/<int:pk>/
    Ek specific ticket aur uske saare messages (chat history) dikhata hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = SupportTicketDetailSerializer

    def get_queryset(self):
        # User sirf apne ticket hi dekh sakta hai
        return SupportTicket.objects.filter(
            user=self.request.user
        ).prefetch_related(
            Prefetch(
                'messages',
                # Sirf non-internal messages ko prefetch karein
                queryset=TicketMessage.objects.filter(is_internal_note=False).select_related('user'),
            )
        )

class AddTicketMessageView(generics.CreateAPIView):
    """
    API: POST /api/support/tickets/<int:ticket_id>/add-message/
    Customer ko apne ticket mein ek naya message add karne deta hai.
    """
    permission_classes = [IsAuthenticated, IsCustomer]
    serializer_class = AddMessageSerializer

    def create(self, request, *args, **kwargs):
        ticket_id = self.kwargs.get('ticket_id')
        user = request.user
        
        try:
            # Check karein ki ticket user ka hi hai
            ticket = SupportTicket.objects.get(id=ticket_id, user=user)
        except SupportTicket.DoesNotExist:
            return Response({"error": "Ticket not found."}, status=status.HTTP_404_NOT_FOUND)
        
        # Check karein ki ticket closed toh nahi hai
        if ticket.status == SupportTicket.TicketStatus.RESOLVED:
             return Response(
                {"error": "This ticket is resolved. Please create a new one if you have issues."}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Message ko create karein (user ko set karke)
        message = serializer.save(
            ticket=ticket,
            user=user,
            is_internal_note=False
        )
        
        # Model ka 'save' method `ticket.status` ko 'OPEN' par set kar dega
        
        # Naya message response mein bhejein
        response_serializer = TicketMessageSerializer(message, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)