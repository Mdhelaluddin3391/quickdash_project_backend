from django.test import TestCase

# Create your tests here.
# wms/tests.py
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import patch # Rider notification ko mock karne ke liye

# Model Imports
from accounts.models import StoreStaffProfile, Address
from store.models import Store, Category, Product, ProductVariant
from inventory.models import StoreInventory
from orders.models import Order, OrderItem
from delivery.models import Delivery
from .models import Location, WmsStock, PickTask

# Function Import
from orders.views import process_successful_payment # Hamara main function

User = get_user_model()

class WmsFullWorkflowTests(APITestCase):

    def setUp(self):
        # 1. Users Banayein
        self.store = Store.objects.create(name="WMS Test Hub")

        # User 1: Manager
        self.manager_user = User.objects.create_user(
            username='manager', 
            phone_number='+91111', 
            password='p1'
        )
        StoreStaffProfile.objects.create(
            user=self.manager_user, 
            store=self.store, 
            is_manager=True, 
            can_pick_orders=False
        )

        # User 2: Picker
        self.picker_user = User.objects.create_user(
            username='picker', 
            phone_number='+91222', 
            password='p2'
        )
        StoreStaffProfile.objects.create(
            user=self.picker_user, 
            store=self.store, 
            is_manager=False, 
            can_pick_orders=True
        )

        # User 3: Customer
        self.customer_user = User.objects.create_user(
            username='customer', 
            phone_number='+91333'
        )
        self.address = Address.objects.create(
            user=self.customer_user, 
            city='Test', 
            full_address='123', 
            pincode='111'
        )

        # 2. Product aur Location Banayein
        cat = Category.objects.create(name='Test', slug='test')
        prod = Product.objects.create(name='Test Product', category=cat)
        var = ProductVariant.objects.create(product=prod, variant_name='1kg', sku='WMS1')

        # Yeh "Summary" stock hai, quantity 0 se shuru hogi
        self.inventory_summary = StoreInventory.objects.create(
            store=self.store,
            variant=var,
            price=100,
            stock_quantity=0 # Signal se update hoga
        )

        # Yeh "Granular" location hai
        self.location = Location.objects.create(
            store=self.store,
            code='RACK-A-01'
        )

        # 3. API URLs
        self.receive_stock_url = reverse('wms-receive-stock')
        self.my_tasks_url = reverse('wms-picker-tasks')

        # Mock rider notification
        self.mock_async_to_sync = patch('wms.views.async_to_sync').start()
        self.mock_get_channel_layer = patch('wms.views.get_channel_layer').start()

    def tearDown(self):
        # Mocks ko stop karein
        patch.stopall()

    def test_full_wms_workflow(self):
        """
        Yeh test poora flow check karta hai:
        1. Manager stock receive karta hai.
        2. Summary stock update hota hai (Signal se).
        3. Customer order place karta hai.
        4. PickTask create hota hai (process_successful_payment se).
        5. Picker task dekhta hai.
        6. Picker task complete karta hai.
        7. Granular stock kam hota hai.
        8. Summary stock phir se update hota hai (Signal se).
        9. Order 'READY_FOR_PICKUP' hota hai.
        """

        # --- 1. WORKFLOW A: Stock Receive (Manager) ---
        self.client.force_authenticate(user=self.manager_user)

        receive_data = {
            'inventory_summary_id': self.inventory_summary.id,
            'location_id': self.location.id,
            'quantity': 100 # 100 units receive kar rahe hain
        }

        response = self.client.post(self.receive_stock_url, receive_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['new_location_quantity'], 100)

        # Check karein ki WmsStock update hua
        wms_stock = WmsStock.objects.get(
            location=self.location, 
            inventory_summary=self.inventory_summary
        )
        self.assertEqual(wms_stock.quantity, 100)

        # Check karein ki Signal ne StoreInventory ko update kiya
        self.inventory_summary.refresh_from_db()
        self.assertEqual(self.inventory_summary.stock_quantity, 100)


        # --- 2. WORKFLOW B: Order Place (Customer) ---
        # Hum 5 unit ka order banayenge

        # Pehle PENDING order banayein
        order = Order.objects.create(
            order_id='test-wms-123',
            user=self.customer_user,
            store=self.store,
            delivery_address=self.address,
            item_subtotal=500,
            final_total=500,
            status=Order.OrderStatus.PENDING,
            payment_status=Order.PaymentStatus.PENDING
        )
        OrderItem.objects.create(
            order=order,
            inventory_item=self.inventory_summary,
            product_name="Test",
            variant_name="1kg",
            price_at_order=100,
            quantity=5 # 5 units
        )

        # Ab 'process_successful_payment' ko manually call karein
        success, result = process_successful_payment(order.order_id)

        self.assertTrue(success)

        # Check karein ki PickTask ban gaya
        self.assertEqual(PickTask.objects.count(), 1)
        task = PickTask.objects.first()

        self.assertEqual(task.order, order)
        self.assertEqual(task.assigned_to, self.picker_user)
        self.assertEqual(task.status, PickTask.PickStatus.PENDING)
        self.assertEqual(task.location, self.location)
        self.assertEqual(task.quantity_to_pick, 5)


        # --- 3. WORKFLOW B: Picker App ---
        self.client.force_authenticate(user=self.picker_user)

        # API se task dekhein
        response = self.client.get(self.my_tasks_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], task.id)

        # Task complete karein
        complete_url = reverse('wms-complete-task', kwargs={'pk': task.id})
        response = self.client.post(complete_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], PickTask.PickStatus.COMPLETED)


        # --- 4. WORKFLOW B: Verification ---

        # Check karein ki task DB mein COMPLETE ho gaya
        task.refresh_from_db()
        self.assertEqual(task.status, PickTask.PickStatus.COMPLETED)

        # Check karein ki Granular Stock (WmsStock) update hua
        wms_stock.refresh_from_db()
        self.assertEqual(wms_stock.quantity, 95) # 100 - 5

        # Check karein ki Signal ne Summary Stock (StoreInventory) ko update kiya
        self.inventory_summary.refresh_from_db()
        self.assertEqual(self.inventory_summary.stock_quantity, 95)

        # Check karein ki Order aur Delivery status update hue
        order.refresh_from_db()
        self.assertEqual(order.status, Order.OrderStatus.READY_FOR_PICKUP)

        delivery = order.delivery
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, Delivery.DeliveryStatus.PENDING_ACCEPTANCE)

        # Check karein ki Rider Notification trigger hua
        self.assertTrue(self.mock_async_to_sync.called)