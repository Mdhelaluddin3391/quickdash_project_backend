from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta # Analytics test ke liye
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
    """
    Dashboard ke main views (Dashboard, Order List, Cancel Item, Manual Pack, Customer Lookup)
    ko test karta hai.
    """

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
        
        # Ek "Low Stock" item banayein
        self.low_stock_inv = StoreInventory.objects.create(
            store=self.store,
            variant=ProductVariant.objects.create(product=prod, variant_name='500g', sku='DASH2'),
            price=50,
            stock_quantity=5 # LOW_STOCK_THRESHOLD (10) se kam
        )


        # 4. Ek Confirmed Order Banayein
        # (Hum process_successful_payment ko call nahi kar rahe taaki hum PickTask khud bana sakein)
        self.order = Order.objects.create(
            order_id='DASH-123',
            user=self.customer_user,
            store=self.store,
            delivery_address=self.address,
            item_subtotal=200,
            final_total=210, # 200 (sub) + 10 (tax)
            taxes_amount=10,
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
        
        # Ek Razorpay Payment object banayein (Refund test karne ke liye)
        self.payment = Payment.objects.create(
            order=self.order,
            payment_method=Payment.PaymentMethod.RAZORPAY,
            amount=self.order.final_total,
            status=Order.PaymentStatus.SUCCESSFUL,
            transaction_id="rzp_test_dash_123"
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

    def test_staff_dashboard_view(self):
        """
        [NAYA TEST] Test: Staff Dashboard API sahi stats return karta hai.
        """
        # Ek "Delivered" order banayein sales check karne ke liye
        Order.objects.create(
            order_id='DASH-456',
            user=self.customer_user, store=self.store, delivery_address=self.address,
            final_total=100,
            status=Order.OrderStatus.DELIVERED, # Delivered
            payment_status=Order.PaymentStatus.SUCCESSFUL
        )
        
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertEqual(Decimal(data['today_sales']), Decimal('100.00')) # Sirf delivered order
        self.assertEqual(data['today_orders_count'], 1) # Sirf delivered
        self.assertEqual(data['pending_pick_tasks'], 1) # Jo humne banaya
        self.assertEqual(data['preparing_orders_count'], 1) # Jo humne banaya
        self.assertEqual(data['ready_for_pickup_orders_count'], 0)
        self.assertEqual(len(data['low_stock_items']), 1)
        self.assertEqual(data['low_stock_items'][0]['id'], self.low_stock_inv.id)

    def test_manager_order_list_filter(self):
        """
        [NAYA TEST] Test: Manager Order List API filtering ke saath kaam karta hai.
        """
        # Ek aur order banayein (CANCELLED)
        Order.objects.create(
            order_id='DASH-789',
            user=self.customer_user, store=self.store, delivery_address=self.address,
            final_total=50, status=Order.OrderStatus.CANCELLED
        )

        # 1. Filter by status 'PREPARING'
        response = self.client.get(f"{self.order_list_url}?status={Order.OrderStatus.PREPARING}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['order_id'], self.order.order_id)

        # 2. Filter by status 'CANCELLED'
        response = self.client.get(f"{self.order_list_url}?status={Order.OrderStatus.CANCELLED}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['order_id'], 'DASH-789')
        
        # 3. Filter by phone
        response = self.client.get(f"{self.order_list_url}?phone={self.customer_user.phone_number}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2) # Dono order
        
        # 4. Filter by order_id
        response = self.client.get(f"{self.order_list_url}?order_id=DASH-123")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)


    @patch('orders.tasks.process_razorpay_refund_task.delay')
    def test_cancel_order_item_fc(self, mock_refund_task):
        """
        Test: Manager 'FC' (Fulfilment Cancel) karta hai.
        (Aapke fix ke saath updated)
        """
        self.assertEqual(self.order.status, Order.OrderStatus.PREPARING)
        self.assertEqual(self.order_item.quantity, 2)
        self.assertEqual(self.order.final_total, Decimal('210.00')) # 200 + 10 tax
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
        self.assertEqual(self.order.final_total, Decimal('105.00'))# 100 (subtotal) + 5 (tax)

        # PickTask check karein (update ho gaya)
        self.pick_task.refresh_from_db()
        self.assertEqual(self.pick_task.status, PickTask.PickStatus.PENDING)
        self.assertEqual(self.pick_task.quantity_to_pick, 1) # Quantity 1 reh gayi

        # Check karein ki partial refund trigger hua
        # 210 (original) - 105 (new) = 105.
        # Refund amount = 105 * 100 = 10500 paise.
        mock_refund_task.assert_called_once_with(
            payment_id=self.payment.id,
            amount_to_refund_paise=10500,
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


class DashboardIssueResolutionTests(APITestCase):
    """
    [NAYA TEST CLASS]
    Specifically PickTask 'ISSUE' flows ko test karta hai.
    """
    
    def setUp(self):
        # 1. Users
        self.store = Store.objects.create(name="Issue Test Hub")
        self.manager_user = User.objects.create_user(
            username='issue_manager', 
            phone_number='+91999111', 
            password='p1'
        )
        self.manager_profile = StoreStaffProfile.objects.create(
            user=self.manager_user, store=self.store, is_manager=True
        )
        self.client.force_authenticate(user=self.manager_user)

        # 2. Product
        cat = Category.objects.create(name='Test Issue', slug='test-issue')
        prod = Product.objects.create(name='Test Product Issue', category=cat)
        var = ProductVariant.objects.create(product=prod, variant_name='1kg', sku='ISSUE1')
        self.inventory_summary = StoreInventory.objects.create(
            store=self.store, variant=var, price=100, stock_quantity=10
        )
        loc = Location.objects.create(store=self.store, code='ISSUE-A-01')

        # 3. Order
        self.order = Order.objects.create(
            order_id='ISSUE-123',
            user=User.objects.create_user(phone_number='+91999222'),
            store=self.store,
            delivery_address=Address.objects.create(user_id=self.manager_user.id, city='t', full_address='t', pincode='t'),
            item_subtotal=100,
            final_total=105, # 100 + 5 tax
            taxes_amount=5,
            status=Order.OrderStatus.PREPARING,
            payment_status=Order.PaymentStatus.SUCCESSFUL
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            inventory_item=self.inventory_summary,
            price_at_order=100,
            quantity=1
        )
        # Payment object (refund ke liye)
        self.payment = Payment.objects.create(
            order=self.order,
            payment_method=Payment.PaymentMethod.RAZORPAY,
            amount=self.order.final_total,
            status=Order.PaymentStatus.SUCCESSFUL,
            transaction_id="rzp_test_issue_123"
        )

        # 4. "ISSUE" PickTask
        self.issue_task = PickTask.objects.create(
            order=self.order,
            location=loc,
            variant=var,
            quantity_to_pick=1,
            status=PickTask.PickStatus.ISSUE, # <-- Main setup
            picker_notes="Picker ko nahi mila"
        )
        
        # 5. URLs
        self.issue_list_url = reverse('staff-issue-tasks')
        self.retry_url = reverse('staff-issue-task-retry', kwargs={'pk': self.issue_task.id})
        self.cancel_url = reverse('staff-issue-task-cancel', kwargs={'pk': self.issue_task.id})

    def test_list_issue_tasks(self):
        """Test: Manager ko 'ISSUE' tasks ki list dikhti hai."""
        response = self.client.get(self.issue_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], self.issue_task.id)
        self.assertEqual(response.data[0]['status'], PickTask.PickStatus.ISSUE)

    def test_resolve_issue_retry(self):
        """Test: Manager task ko 'RETRY' kar sakta hai."""
        response = self.client.post(self.retry_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.issue_task.refresh_from_db()
        self.assertEqual(self.issue_task.status, PickTask.PickStatus.PENDING)
        self.assertIsNone(self.issue_task.assigned_to) # Unassigned ho gaya
        self.assertIn("[Issue Resolved by", self.issue_task.picker_notes)

    @patch('orders.tasks.process_razorpay_refund_task.delay')
    def test_resolve_issue_cancel_and_refund(self, mock_refund_task):
        """Test: Manager task ko 'CANCEL' kar sakta hai (aur refund trigger hota hai)."""
        response = self.client.post(self.cancel_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # 1. Task check karein
        self.issue_task.refresh_from_db()
        self.assertEqual(self.issue_task.status, PickTask.PickStatus.CANCELLED)
        
        # 2. OrderItem check karein (delete ho gaya)
        self.assertFalse(OrderItem.objects.filter(id=self.order_item.id).exists())
        
        # 3. Order total check karein
        self.order.refresh_from_db()
        self.assertEqual(self.order.item_subtotal, Decimal('0.00'))
        self.assertEqual(self.order.taxes_amount, Decimal('0.00'))
        self.assertEqual(self.order.final_total, Decimal('0.00')) # Sirf delivery fee/tip bachegi (jo 0 thi)
        
        # 4. Refund check karein
        # Poora 105 refund hona chahiye
        mock_refund_task.assert_called_once_with(
            payment_id=self.payment.id,
            amount_to_refund_paise=10500,
            is_partial_refund=True
        )


class DashboardAnalyticsTests(APITestCase):
    """
    [NAYA TEST CLASS]
    Analytics Dashboard view ko test karta hai.
    """
    def setUp(self):
        self.store = Store.objects.create(name="Analytics Hub")
        self.manager_user = User.objects.create_user(
            username='analytics_manager', 
            phone_number='+91777111', 
            password='p1'
        )
        StoreStaffProfile.objects.create(
            user=self.manager_user, store=self.store, is_manager=True
        )
        self.client.force_authenticate(user=self.manager_user)
        
        # Data banayein
        # Pincode 1
        addr1 = Address.objects.create(user_id=self.manager_user.id, city='t', full_address='t', pincode='560001')
        # Pincode 2
        addr2 = Address.objects.create(user_id=self.manager_user.id, city='t', full_address='t', pincode='560002')

        # Order 1 (Today)
        order1 = Order.objects.create(
            store=self.store, status=Order.OrderStatus.DELIVERED,
            delivery_address=addr1, final_total=100,
            created_at=timezone.now() - timedelta(hours=1)
        )
        # Order 2 (Today)
        order2 = Order.objects.create(
            store=self.store, status=Order.OrderStatus.DELIVERED,
            delivery_address=addr2, final_total=150,
            created_at=timezone.now() - timedelta(hours=2)
        )
        # Order 3 (Last Week)
        order3 = Order.objects.create(
            store=self.store, status=Order.OrderStatus.DELIVERED,
            delivery_address=addr1, final_total=50,
            created_at=timezone.now() - timedelta(days=5)
        )
        
        self.analytics_url = reverse('staff-analytics')

    def test_analytics_today(self):
        """Test: Analytics 'today' filter ke saath."""
        response = self.client.get(f"{self.analytics_url}?period=today")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertEqual(data['total_orders'], 2)
        self.assertEqual(Decimal(data['total_revenue']), Decimal('250.00')) # 100 + 150
        self.assertEqual(Decimal(data['average_order_value']), Decimal('125.00')) # 250 / 2
        self.assertEqual(len(data['top_pincodes']), 2)

    def test_analytics_last_week(self):
        """Test: Analytics 'last_week' filter ke saath."""
        response = self.client.get(f"{self.analytics_url}?period=last_week")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        data = response.data
        self.assertEqual(data['total_orders'], 3)
        self.assertEqual(Decimal(data['total_revenue']), Decimal('300.00')) # 100 + 150 + 50
        self.assertEqual(Decimal(data['average_order_value']), Decimal('100.00')) # 300 / 3
        
        # Top pincode 560001 hona chahiye (2 orders)
        self.assertEqual(data['top_pincodes'][0]['pincode'], '560001')
        self.assertEqual(data['top_pincodes'][0]['order_count'], 2)