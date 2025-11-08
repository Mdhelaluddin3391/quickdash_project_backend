# In orders/tests.py

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.gis.geos import Point
from accounts.models import User, Address
from store.models import Category, Product, ProductVariant, Store
from inventory.models import StoreInventory
from cart.models import Cart, CartItem
from orders.models import Order, OrderItem, Payment, Coupon # Coupon import karein
from delivery.models import Delivery 
from decimal import Decimal
from django.utils import timezone
import datetime

# --- Settings ko Mock/Override karne ke liye ---
from django.test import override_settings

# Database mein 20.00, 5.00, etc. save karne ke liye
# Humein settings.py mein define ki gayi values yahaan mock karni hongi
@override_settings(
    BASE_DELIVERY_FEE=Decimal('20.00'),
    FEE_PER_KM=Decimal('5.00'),
    MIN_DELIVERY_FEE=Decimal('20.00'),
    MAX_DELIVERY_FEE=Decimal('100.00'),
    TAX_RATE=Decimal('0.05') # 5% tax
)
class OrderFlowTests(APITestCase):

    def setUp(self):
        """Ek poora environment setup karein: User, Store, Product, Inventory, Cart."""
        
        self.user = User.objects.create_user(username='orderuser', phone_number='+911234567890', password='testpass123')
        self.client.force_authenticate(user=self.user)
        
        self.address = Address.objects.create(
            user=self.user,
            full_address='123 Main St',
            city='Testville',
            pincode='123456',
            location=Point(77.0, 12.0) # 0 km distance
        )
        
        self.cart = Cart.objects.create(user=self.user)

        self.store = Store.objects.create(name='Main Hub', location=Point(77.0, 12.0)) # 0 km distance
        
        cat = Category.objects.create(name='Drinks', slug='drinks')
        prod = Product.objects.create(name='Cola', category=cat)
        var = ProductVariant.objects.create(product=prod, variant_name='1L', sku='COLA1')
        
        self.inventory_item = StoreInventory.objects.create(
            store=self.store,
            variant=var,
            price=100.00, # Current price ₹100
            stock_quantity=10 
        )
        
        # Cart mein 2 item add karein (Total ₹200)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            inventory_item=self.inventory_item,
            quantity=2
        )
        
        self.checkout_url = reverse('checkout')

        # --- Naye Coupons banayein ---
        self.coupon_fixed = Coupon.objects.create(
            code="SAVE50",
            discount_type=Coupon.DiscountType.FIXED_AMOUNT,
            discount_value=50.00,
            valid_from=timezone.now() - datetime.timedelta(days=1),
            valid_to=timezone.now() + datetime.timedelta(days=1),
            min_purchase_amount=150.00
        )
        
        self.coupon_percent = Coupon.objects.create(
            code="SAVE10",
            discount_type=Coupon.DiscountType.PERCENTAGE,
            discount_value=10.00, # 10%
            valid_from=timezone.now() - datetime.timedelta(days=1),
            valid_to=timezone.now() + datetime.timedelta(days=1),
            min_purchase_amount=100.00
        )
        
        self.coupon_expired = Coupon.objects.create(
            code="EXPIRED",
            discount_type=Coupon.DiscountType.FIXED_AMOUNT,
            discount_value=20.00,
            valid_from=timezone.now() - datetime.timedelta(days=2),
            valid_to=timezone.now() - datetime.timedelta(days=1), # Expired
        )

    def test_checkout_cod_basic(self):
        """Test karein ki basic COD checkout sahi calculation karta hai."""
        
        self.assertEqual(Order.objects.count(), 0) 
        
        data = {
            'delivery_address_id': self.address.id,
            'payment_method': 'COD'
            # No coupon, no tip
        }
        response = self.client.post(self.checkout_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('order_details', response.data)
        
        order = Order.objects.first()
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.status, Order.OrderStatus.CONFIRMED) # COD turant confirm hota hai
        
        # Calculation check karein:
        # Subtotal = 2 * 100 = 200
        # Discount = 0
        # Delivery Fee = 20 (MIN_DELIVERY_FEE)
        # Taxable = 200 (subtotal - discount)
        # Tax = 200 * 0.05 = 10
        # Tip = 0
        # Total = (200 - 0) + 20 + 10 + 0 = 230
        
        self.assertEqual(order.item_subtotal, Decimal('200.00'))
        self.assertEqual(order.discount_amount, Decimal('0.00'))
        self.assertEqual(order.delivery_fee, Decimal('20.00'))
        self.assertEqual(order.taxes_amount, Decimal('10.00'))
        self.assertEqual(order.rider_tip, Decimal('0.00'))
        self.assertEqual(order.final_total, Decimal('230.00'))
        
        # Check karein ki stock update hua
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.stock_quantity, 8) # 10 - 2
        
        # Check karein ki cart khaali hua
        self.assertEqual(self.cart.items.count(), 0)

    def test_checkout_with_fixed_coupon(self):
        """Test karein ki fixed amount coupon sahi se apply hota hai."""
        data = {
            'delivery_address_id': self.address.id,
            'payment_method': 'COD',
            'coupon_code': 'SAVE50' # ₹50 discount
        }
        response = self.client.post(self.checkout_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        order = Order.objects.first()
        
        # Calculation check karein:
        # Subtotal = 200
        # Discount = 50
        # Delivery Fee = 20
        # Taxable = 200 - 50 = 150
        # Tax = 150 * 0.05 = 7.50
        # Tip = 0
        # Total = (200 - 50) + 20 + 7.50 + 0 = 177.50
        
        self.assertEqual(order.item_subtotal, Decimal('200.00'))
        self.assertEqual(order.discount_amount, Decimal('50.00'))
        self.assertEqual(order.taxes_amount, Decimal('7.50'))
        self.assertEqual(order.final_total, Decimal('177.50'))
        self.assertEqual(order.coupon, self.coupon_fixed)
        
        # Check karein ki coupon usage count badh gaya
        self.coupon_fixed.refresh_from_db()
        self.assertEqual(self.coupon_fixed.times_used, 1)

    def test_checkout_with_percent_coupon(self):
        """Test karein ki percentage coupon sahi se apply hota hai."""
        data = {
            'delivery_address_id': self.address.id,
            'payment_method': 'COD',
            'coupon_code': 'SAVE10' # 10% discount
        }
        response = self.client.post(self.checkout_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        order = Order.objects.first()
        
        # Calculation check karein:
        # Subtotal = 200
        # Discount = 10% of 200 = 20
        # Delivery Fee = 20
        # Taxable = 200 - 20 = 180
        # Tax = 180 * 0.05 = 9.00
        # Tip = 0
        # Total = (200 - 20) + 20 + 9.00 + 0 = 209.00
        
        self.assertEqual(order.item_subtotal, Decimal('200.00'))
        self.assertEqual(order.discount_amount, Decimal('20.00'))
        self.assertEqual(order.taxes_amount, Decimal('9.00'))
        self.assertEqual(order.final_total, Decimal('209.00'))
        self.assertEqual(order.coupon, self.coupon_percent)

    def test_checkout_with_rider_tip(self):
        """Test karein ki rider tip sahi se add hoti hai."""
        data = {
            'delivery_address_id': self.address.id,
            'payment_method': 'COD',
            'rider_tip': '25.00' # ₹25 tip
        }
        response = self.client.post(self.checkout_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        order = Order.objects.first()
        
        # Calculation check karein:
        # Subtotal = 200
        # Discount = 0
        # Delivery Fee = 20
        # Taxable = 200 - 0 = 200
        # Tax = 200 * 0.05 = 10
        # Tip = 25
        # Total = (200 - 0) + 20 + 10 + 25 = 255.00
        
        self.assertEqual(order.item_subtotal, Decimal('200.00'))
        self.assertEqual(order.rider_tip, Decimal('25.00'))
        self.assertEqual(order.final_total, Decimal('255.00'))

    def test_checkout_with_coupon_and_tip(self):
        """Test karein ki coupon aur tip dono ek saath sahi se apply hote hain."""
        data = {
            'delivery_address_id': self.address.id,
            'payment_method': 'COD',
            'coupon_code': 'SAVE50', # ₹50 discount
            'rider_tip': '25.00'      # ₹25 tip
        }
        response = self.client.post(self.checkout_url, data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        order = Order.objects.first()
        
        # Calculation check karein:
        # Subtotal = 200
        # Discount = 50
        # Delivery Fee = 20
        # Taxable = 200 - 50 = 150
        # Tax = 150 * 0.05 = 7.50
        # Tip = 25
        # Total = (200 - 50) + 20 + 7.50 + 25 = 202.50
        
        self.assertEqual(order.item_subtotal, Decimal('200.00'))
        self.assertEqual(order.discount_amount, Decimal('50.00'))
        self.assertEqual(order.rider_tip, Decimal('25.00'))
        self.assertEqual(order.taxes_amount, Decimal('7.50'))
        self.assertEqual(order.final_total, Decimal('202.50'))

    def test_checkout_fail_invalid_coupon(self):
        """Test karein ki galat coupon code fail hota hai."""
        data = {'delivery_address_id': self.address.id, 'coupon_code': 'INVALIDCODE'}
        response = self.client.post(self.checkout_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Invalid coupon code', str(response.data['coupon_code']))
        self.assertEqual(Order.objects.count(), 0) # Order create nahi hona chahiye

    def test_checkout_fail_expired_coupon(self):
        """Test karein ki expired coupon fail hota hai."""
        data = {'delivery_address_id': self.address.id, 'coupon_code': 'EXPIRED'}
        response = self.client.post(self.checkout_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Coupon has expired', str(response.data['coupon_code']))
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_fail_min_purchase(self):
        """Test karein ki minimum purchase amount check hota hai."""
        # Min purchase ₹150 hai, humara cart total ₹200 hai (toh pass hoga)
        # Hum cart total ko ₹100 karte hain
        self.cart_item.quantity = 1
        self.cart_item.save() # Ab cart total ₹100 hai
        
        data = {'delivery_address_id': self.address.id, 'coupon_code': 'SAVE50'} # SAVE50 ko ₹150 chahiye
        response = self.client.post(self.checkout_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Minimum purchase of ₹150.00 required', str(response.data['error']))
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_razorpay_creates_pending_order(self):
        """Test karein ki Razorpay checkout PENDING order banata hai (COD ki tarah confirm nahi)."""
        data = {
            'delivery_address_id': self.address.id,
            'payment_method': 'RAZORPAY'
        }
        response = self.client.post(self.checkout_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('razorpay_order_id', response.data) # Razorpay details aani chahiye
        
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.status, Order.OrderStatus.PENDING) # Order PENDING hona chahiye
        
        # Stock update nahi hona chahiye
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.stock_quantity, 10)
        
        # Cart khaali nahi hona chahiye
        self.assertEqual(self.cart.items.count(), 1)

    def test_order_cancellation_pending(self):
        """Test karein ki PENDING order cancel ho sakta hai (stock revert nahi hoga)."""
        # Pehle ek PENDING order banayein
        self.test_checkout_razorpay_creates_pending_order()
        
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.status, Order.OrderStatus.PENDING)
        
        # Cancellation API call karein
        cancel_url = reverse('order-cancel', kwargs={'order_id': order.order_id})
        response = self.client.post(cancel_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertEqual(order.status, Order.OrderStatus.CANCELLED)
        
        # Stock revert nahi hona chahiye, kyunki PENDING order mein stock cut nahi hua tha
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.stock_quantity, 10)

    def test_order_cancellation_confirmed_stock_revert(self):
        """Test karein ki CONFIRMED order cancel karne par stock revert hota hai."""
        # Pehle ek CONFIRMED order banayein (COD se)
        self.test_checkout_cod_basic()
        
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.status, Order.OrderStatus.CONFIRMED)
        
        # Stock check karein (cut ho chuka hai)
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.stock_quantity, 8)
        
        # Cancellation API call karein
        cancel_url = reverse('order-cancel', kwargs={'order_id': order.order_id})
        response = self.client.post(cancel_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        order.refresh_from_db()
        self.assertEqual(order.status, Order.OrderStatus.CANCELLED)
        
        # Stock check karein (wapas add ho jaana chahiye)
        self.inventory_item.refresh_from_db()
        self.assertEqual(self.inventory_item.stock_quantity, 10) # 8 + 2