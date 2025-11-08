from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.gis.geos import Point
from accounts.models import User, Address, StoreStaffProfile
from delivery.models import RiderProfile, Delivery
from store.models import Category, Product, ProductVariant, Store
from inventory.models import StoreInventory
from cart.models import Cart, CartItem
from orders.models import Order

from unittest.mock import patch

class DeliveryFlowTests(APITestCase):

    def setUp(self):
        """
        Ek poora flow setup karein:
        1. Customer
        2. Store Staff
        3. Rider
        4. Ek 'CONFIRMED' Order (jiska 'Delivery' object bhi bana hua hai)
        """
        
        self.customer_user = User.objects.create_user(username='customer', phone_number='+91111')
        self.address = Address.objects.create(
            user=self.customer_user, 
            city='Cust City', 
            full_address='123 Test', 
            pincode='111000'
)
        
        self.staff_user = User.objects.create_user(username='staff', phone_number='+91222')
        self.rider_user = User.objects.create_user(username='rider', phone_number='+91333')
        
        self.store = Store.objects.create(name='Test Hub', location=Point(77.0, 12.0))
        
        StoreStaffProfile.objects.create(user=self.staff_user, store=self.store)
        
        self.rider_profile = RiderProfile.objects.create(
            user=self.rider_user, 
            current_location=Point(77.01, 12.01, srid=4326) 
        )


        self.order = Order.objects.create(
            user=self.customer_user,
            store=self.store,
            delivery_address=self.address,
            status=Order.OrderStatus.CONFIRMED, 
            payment_status=Order.PaymentStatus.SUCCESSFUL,
            item_subtotal=100,
            final_total=100
        )
        
        self.delivery = Delivery.objects.create(
            order=self.order,
            status=Delivery.DeliveryStatus.AWAITING_PREPARATION 
        )

    @patch('delivery.views.async_to_sync') 
    @patch('delivery.views.get_channel_layer') 
    def test_full_delivery_workflow(self, mock_get_layer, mock_async_to_sync):
        """
        Poora flow test karein:
        1. Staff naye order dekhta hai.
        2. Staff order ko 'READY_FOR_PICKUP' mark karta hai.
        3. Rider available orders dekhta hai.
        4. Rider order accept karta hai.
        5. Rider location update karta hai.
        6. Rider status 'PICKED_UP' karta hai.
        7. Rider status 'DELIVERED' karta hai.
        """
        
        self.client.force_authenticate(user=self.staff_user)
        url_staff_orders = reverse('staff-new-orders')
        response = self.client.get(url_staff_orders)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['order_id'], self.order.order_id)
        
        url_staff_update = reverse('staff-update-order', kwargs={'order_id': self.order.order_id})
        data_preparing = {'status': Order.OrderStatus.PREPARING}
        response = self.client.post(url_staff_update, data_preparing)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.OrderStatus.PREPARING)
        
     
        data_ready = {'status': Order.OrderStatus.READY_FOR_PICKUP}
        response = self.client.post(url_staff_update, data_ready)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.order.status, Order.OrderStatus.READY_FOR_PICKUP)
        self.assertEqual(self.delivery.status, Delivery.DeliveryStatus.PENDING_ACCEPTANCE)

        self.assertTrue(mock_async_to_sync.called)
        
        self.client.force_authenticate(user=self.rider_user)
        self.rider_profile.is_online = True
        self.rider_profile.save()
        
        url_available = reverse('available-deliveries')
        response = self.client.get(url_available)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['order_id'], self.order.order_id)
        self.assertIn('distance_to_store', response.data[0])

        url_accept = reverse('accept-delivery', kwargs={'pk': self.delivery.id})
        response = self.client.post(url_accept)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.delivery.refresh_from_db()
        self.rider_profile.refresh_from_db()
        self.assertEqual(self.delivery.status, Delivery.DeliveryStatus.ACCEPTED)
        self.assertEqual(self.delivery.rider, self.rider_profile)
        self.assertTrue(self.rider_profile.on_delivery) 

        url_location = reverse('rider-update-location')
        data_location = {'latitude': 12.05, 'longitude': 77.05}
        response = self.client.patch(url_location, data_location)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.rider_profile.refresh_from_db()
        self.assertEqual(self.rider_profile.current_location.y, 12.05)

        url_update = reverse('update-delivery-status', kwargs={'pk': self.delivery.id})
        data_at_store = {'status': Delivery.DeliveryStatus.AT_STORE}
        response = self.client.post(url_update, data_at_store)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data_picked_up = {'status': Delivery.DeliveryStatus.PICKED_UP}
        response = self.client.post(url_update, data_picked_up)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.order.status, Order.OrderStatus.OUT_FOR_DELIVERY)
        self.assertEqual(self.delivery.status, Delivery.DeliveryStatus.PICKED_UP)

        data_delivered = {'status': Delivery.DeliveryStatus.DELIVERED}
        response = self.client.post(url_update, data_delivered)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.delivery.refresh_from_db()
        self.rider_profile.refresh_from_db()
        
        self.assertEqual(self.order.status, Order.OrderStatus.DELIVERED)
        self.assertEqual(self.delivery.status, Delivery.DeliveryStatus.DELIVERED)
        self.assertFalse(self.rider_profile.on_delivery) 