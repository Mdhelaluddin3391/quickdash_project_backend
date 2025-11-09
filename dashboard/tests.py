from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from unittest.mock import patch # Celery aur Notifications ko mock karne ke liye

# Model Imports
from accounts.models import StoreStaffProfile, Address
from store.models import Store, Category, Product, ProductVariant
from inventory.models import StoreInventory
from orders.models import Order, OrderItem, Payment, Coupon
from delivery.models import Delivery
from wms.models import Location, WmsStock, PickTask

User = get_user_model()

class DashboardAPITests(APITestCase):

    def setUp(self):
        """
        Ek poora environment setup karein:
        Manager, Customer, Store, Products, WMS Stock, aur ek Confirmed Order.
        """
        # 1. Users Banayein
        self.store = Store.objects.create(name="Dashboard Test Hub")

        # User 1: Manager
        self.manager_user = User.objects.create_user(
            username='manager_dash', 
            phone_number='+91888111', 
            password='p1'
        )
        self.manager_profile = StoreStaffProfile.objects.create(
            user=self.manager_user, 
            store=self.store, 
            is_manager=True, 
            can_pick_orders=True # Manager pick bhi kar sakta hai
        )

        # User 2: Customer
        self.customer_user = User.objects.create_user(
            username='cust_dash', 
            phone_number='+91888222'
        )
        self.address = Address.objects.create(
            user=self.customer_user, 
            city='Test', 
            full_address='123', 
            pincode='111'
        )

        # 3. Product aur WMS Stock Setup
        cat = Category.objects.create(name='Test Dash', slug='test-dash')
        prod = Product.objects.create(name='Test Product Dash', category=cat)
        var = ProductVariant.objects.create(product=prod, variant_name='1kg', sku='DASH1')

        # Summary stock
        self.inventory_summary = StoreInventory.objects.create(
            store=self.store,
            variant=var,
            price=100,
            stock_quantity=0 # Signal se update hoga
        )

        # Granular stock
        self.location = Location.objects.create(store=self.store, code='DASH-A-01')
        self.wms_stock = WmsStock.objects.create(
            inventory_summary=self.inventory_summary,
            location=self.location,
            quantity=50 # Hamare paas 50 unit hain
        )
        # Signal ne summary stock ko 50 kar diya hoga
        self.inventory_summary.refresh_from_db()
        self.assertEqual(self.inventory_summary.stock_quantity, 50)

        # 4. Ek Confirmed Order Banayein
        # (Hum process_successful_payment ko call nahi kar rahe taaki hum PickTask khud bana sakein)
        self.order = Order.objects.create(
            order_id='DASH-123',
            user=self.customer_user,
            store=self.store,
            delivery_address=self.address,
            item_subtotal=200,
            final_total=200,
            status=Order.OrderStatus.PREPARING, # PREPARING state mein
            payment_status=Order.PaymentStatus.SUCCESSFUL
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            inventory_item=self.inventory_summary,
            product_name="Test Product Dash",
            variant_name="1kg",
            price_at_order=100,
            quantity=2 # 2 units ka order
        )
        self.delivery = Delivery.objects.create(
            order=self.order, 
            status=Delivery.DeliveryStatus.AWAITING_PREPARATION
        )
        
        # 5. Is Order ke liye PickTask Banayein
        self.pick_task = PickTask.objects.create(
            order=self.order,
            location=self.location,
            variant=var,
            quantity_to_pick=2, # 2 unit pick karna hai
            assigned_to=self.manager_user, # Kisi ko assign kar dete hain
            status=PickTask.PickStatus.PENDING
        )

        # 6. URLs
        self.dashboard_url = reverse('staff-dashboard')
        self.order_list_url = reverse('staff-order-list')
        self.cancel_item_url = reverse('staff-cancel-item')
        self.manual_pack_url = reverse('staff-mark-packed', kwargs={'order_id': self.order.order_id})
        self.customer_lookup_url = reverse('staff-customer-lookup')

        # 7. Manager ko login karein
        self.client.force_authenticate(user=self.manager_user)

    @patch('orders.tasks.process_razorpay_refund_task.delay')
    def test_cancel_order_item_fc(self, mock_refund_task):
        """
        Test: Manager 'FC' (Fulfilment Cancel) karta hai.
        """
        self.assertEqual(self.order.status, Order.OrderStatus.PREPARING)
        self.assertEqual(self.order_item.quantity, 2)
        self.assertEqual(self.order.final_total, Decimal('200.00'))
        self.assertEqual(self.pick_task.status, PickTask.PickStatus.PENDING)

        data = {
            "order_item_id": self.order_item.id,
            "quantity_to_cancel": 1 # 2 mein se 1 cancel kar rahe hain
        }
        
        response = self.client.post(self.cancel_item_url, data)
        
        # Check Response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # OrderItem check karein
        self.order_item.refresh_from_db()
        self.assertEqual(self.order_item.quantity, 1) # Quantity 1 reh gayi

        # Order total check karein (recalculate ho gaya)
        self.order.refresh_from_db()
        # Subtotal = 100, Tax = 5 (0.05*100), Total = 105
        self.assertEqual(self.order.item_subtotal, Decimal('100.00'))
        self.assertEqual(self.order.taxes_amount, Decimal('5.00'))
        self.assertEqual(self.order.final_total, Decimal('105.00')) # 100 (subtotal) + 5 (tax)

        # PickTask check karein (update ho gaya)
        self.pick_task.refresh_from_db()
        self.assertEqual(self.pick_task.status, PickTask.PickStatus.PENDING)
        self.assertEqual(self.pick_task.quantity_to_pick, 1) # Quantity 1 reh gayi

        # Refund task check karein (call hua)
        amount_to_refund = Decimal('200.00') - Decimal('105.00') # 95
        mock_refund_task.assert_called_once_with(
            payment_id=None, # Humne payment object nahi banaya tha, isliye None
            amount_to_refund_paise=int(amount_to_refund * 100),
            is_partial_refund=True
        )

    @patch('delivery.utils.notify_nearby_riders')
    def test_manual_pack(self, mock_notify_riders):
        """
        Test: Manager 'Manual Pack' karta hai.
        """
        self.assertEqual(self.wms_stock.quantity, 50)
        
        response = self.client.post(self.manual_pack_url)
        
        # Check Response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Order aur Delivery status check karein
        self.order.refresh_from_db()
        self.delivery.refresh_from_db()
        self.assertEqual(self.order.status, Order.OrderStatus.READY_FOR_PICKUP)
        self.assertEqual(self.delivery.status, Delivery.DeliveryStatus.PENDING_ACCEPTANCE)

        # PickTask status check karein
        self.pick_task.refresh_from_db()
        self.assertEqual(self.pick_task.status, PickTask.PickStatus.COMPLETED)

        # "Superb" WMS stock check
        self.wms_stock.refresh_from_db()
        self.assertEqual(self.wms_stock.quantity, 48) # 50 - 2
        
        # Check karein ki WMS Signal ne summary stock bhi update kar diya
        self.inventory_summary.refresh_from_db()
        self.assertEqual(self.inventory_summary.stock_quantity, 48)

        # Check karein ki riders ko notify kiya gaya
        mock_notify_riders.assert_called_once()

    def test_customer_lookup(self):
        """
        Test: Manager customer ki details search karta hai.
        """
        url = f"{self.customer_lookup_url}?phone={self.customer_user.phone_number}"
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['phone_number'], self.customer_user.phone_number)
        self.assertIn('profile', response.data)
        self.assertIn('addresses', response.data)
        self.assertEqual(len(response.data['addresses']), 1)
        self.assertEqual(response.data['addresses'][0]['pincode'], '111')

    def test_customer_lookup_fail_not_found(self):
        """
        Test: Manager galat phone number search karta hai.
        """
        url = f"{self.customer_lookup_url}?phone=+91000000"
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('koi customer nahi mila', response.data['error'])