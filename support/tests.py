from django.test import TestCase

# Create your tests here.
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model

# Model Imports
from accounts.models import Address
from store.models import Store
from orders.models import Order
from .models import SupportTicket, TicketMessage, SupportTicket

User = get_user_model()

class SupportTicketAPITests(APITestCase):

    def setUp(self):
        # 1. Users Banayein
        self.customer_user = User.objects.create_user(
            username='support_user', 
            phone_number='+91999111', 
            password='p1',
            first_name='Test',
            last_name='User'
        )
        self.other_user = User.objects.create_user(
            username='other_user', 
            phone_number='+91999222', 
            password='p2'
        )
        
        # 2. Customer ko login karein
        self.client.force_authenticate(user=self.customer_user)

        # 3. Ek Order Banayein (Ticket ke saath link karne ke liye)
        store = Store.objects.create(name="Support Test Store")
        address = Address.objects.create(user=self.customer_user, city='Test', full_address='123', pincode='111')
        self.order = Order.objects.create(
            order_id='SUPPORT-001',
            user=self.customer_user,
            store=store,
            delivery_address=address,
            final_total=100,
            status=Order.OrderStatus.DELIVERED
        )

        # 4. URLs
        self.list_create_url = reverse('support-ticket-list-create')

        # 5. Ek ticket pehle se banayein (GET aur POST Message test karne ke liye)
        self.ticket1 = SupportTicket.objects.create(
            user=self.customer_user,
            subject="Puraana issue",
            category=SupportTicket.TicketCategory.ORDER_ISSUE,
            order=self.order,
            status=SupportTicket.TicketStatus.PENDING # Maan lo staff ne reply kiya tha
        )
        TicketMessage.objects.create(
            ticket=self.ticket1,
            user=self.customer_user, # Pehla message customer ka
            message="Mera order kahan hai?"
        )
        
        self.detail_url = reverse('support-ticket-detail', kwargs={'pk': self.ticket1.id})
        self.add_message_url = reverse('support-ticket-add-message', kwargs={'ticket_id': self.ticket1.id})

    def test_create_ticket_success(self):
        """
        Test: Customer ek naya support ticket (bina order ke) create kar sakta hai.
        """
        data = {
            "subject": "Naya Issue: App crash",
            "category": "TECHNICAL_ISSUE",
            "message": "Meri app login par crash ho rahi hai."
        }
        
        response = self.client.post(self.list_create_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SupportTicket.objects.count(), 2) # Ek setup mein, ek abhi
        self.assertEqual(TicketMessage.objects.count(), 2)
        
        new_ticket = SupportTicket.objects.latest('id')
        self.assertEqual(new_ticket.subject, "Naya Issue: App crash")
        self.assertEqual(new_ticket.user, self.customer_user)
        self.assertEqual(new_ticket.status, SupportTicket.TicketStatus.OPEN) # Naya ticket 'OPEN' hona chahiye

    def test_create_ticket_with_order_success(self):
        """
        Test: Customer ek naya ticket (order ke saath) create kar sakta hai.
        """
        data = {
            "subject": "Order mein item missing tha",
            "category": "ORDER_ISSUE",
            "message": "Mujhe 2 ke bajaye 1 item mila.",
            "order_id": self.order.order_id # Order ID pass karein
        }
        
        response = self.client.post(self.list_create_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_ticket = SupportTicket.objects.latest('id')
        self.assertEqual(new_ticket.order, self.order) # Check karein ki order link hua

    def test_list_tickets(self):
        """
        Test: Customer apne tickets ki list dekh sakta hai.
        """
        # Ek aur ticket banayein (taaki list mein 2 ho)
        self.test_create_ticket_success() # Isse 2 ticket ho jayenge
        
        response = self.client.get(self.list_create_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Naye tests mein list mein 2 item hone chahiye
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]['subject'], "Naya Issue: App crash") # Latest pehle
        self.assertEqual(response.data[1]['subject'], "Puraana issue")

    def test_get_ticket_detail_success(self):
        """
        Test: Customer apne ticket ki poori detail (messages ke saath) dekh sakta hai.
        """
        response = self.client.get(self.detail_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['subject'], self.ticket1.subject)
        self.assertEqual(response.data['ticket_id'], self.ticket1.ticket_id)
        self.assertEqual(len(response.data['messages']), 1)
        self.assertEqual(response.data['messages'][0]['message'], "Mera order kahan hai?")

    def test_get_ticket_detail_security_fail(self):
        """
        Test (Security): Ek customer doosre customer ka ticket nahi dekh sakta.
        """
        # Doosre user se login karein
        self.client.force_authenticate(user=self.other_user)
        
        # Pehle user ka ticket access karne ki koshish karein
        response = self.client.get(self.detail_url)
        
        # 404 Not Found aana chahiye
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_add_message_success_and_status_update(self):
        """
        Test: Customer ticket mein naya message add kar sakta hai
        aur check karein ki ticket ka status 'OPEN' ho gaya.
        """
        # Pehle check karein ki ticket 'PENDING' hai (setup se)
        self.assertEqual(self.ticket1.status, SupportTicket.TicketStatus.PENDING)

        data = {
            "message": "Hello? Koi hai? Please reply."
        }
        response = self.client.post(self.add_message_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['message'], "Hello? Koi hai? Please reply.")
        
        # Check karein ki message DB mein add hua
        self.assertEqual(self.ticket1.messages.count(), 2)
        
        # "Superb" Test: Check karein ki model ka save() signal trigger hua
        self.ticket1.refresh_from_db()
        self.assertEqual(self.ticket1.status, SupportTicket.TicketStatus.OPEN)