from django.urls import path
from .views import (
    SupportTicketListCreateView,
    SupportTicketDetailView,
    AddTicketMessageView
)

urlpatterns = [
    # /api/support/tickets/ (GET, POST)
    path('tickets/', 
         SupportTicketListCreateView.as_view(), 
         name='support-ticket-list-create'),
    
    # /api/support/tickets/123/ (GET)
    # Hum 'id' (PK) use kar rahe hain, 'ticket_id' (string) nahi,
    # kyunki yeh standard tareeka hai.
    path('tickets/<int:pk>/', 
         SupportTicketDetailView.as_view(), 
         name='support-ticket-detail'),
    
    # /api/support/tickets/123/add-message/ (POST)
    path('tickets/<int:ticket_id>/add-message/', 
         AddTicketMessageView.as_view(), 
         name='support-ticket-add-message'),
]