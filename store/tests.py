# In store/tests.py

from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.gis.geos import Point
from store.models import Category, Store, Product, ProductVariant, Review # Review import karein
from accounts.models import User, Address
from orders.models import Order, OrderItem
from inventory.models import StoreInventory
from decimal import Decimal

class StoreAPITests(APITestCase):

    def setUp(self):
        self.parent_cat = Category.objects.create(name='Fruits & Veg', slug='fruits-veg')
        self.child_cat = Category.objects.create(
            name='Fresh Fruits', 
            slug='fresh-fruits', 
            parent=self.parent_cat
        )
        
        self.store1 = Store.objects.create(
            name='Koramangala Hub',
            address='Koramangala, Bengaluru',
            location=Point(77.6160, 12.9352, srid=4326) 
        )
        self.store2 = Store.objects.create(
            name='Indiranagar Hub',
            address='Indiranagar, Bengaluru',
            location=Point(77.6412, 12.9719, srid=4326) 
        )
        
        self.category_list_url = reverse('category-list')
        self.store_list_url = reverse('store-list')

    def test_list_categories(self):
        """Test karein ki sabhi active categories list hoti hain."""
        response = self.client.get(self.category_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        child_data = next(item for item in response.data if item['slug'] == 'fresh-fruits')
        self.assertEqual(child_data['parent'], self.parent_cat.id)

    def test_list_stores_default(self):
        """Test karein ki stores default (by name/id) list hote hain."""
        response = self.client.get(self.store_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        # Default ordering ab 'created_at' hai
        self.assertEqual(response.data[0]['name'], 'Indiranagar Hub')

    def test_list_stores_sorted_by_distance(self):
        """CRITICAL: Test karein ki GeoDjango query (lat/lng) sahi kaam kar rahi hai."""
        
        user_lat = 12.9749 # Indiranagar ke paas
        user_lng = 77.6095 # Indiranagar ke paas
        
        
        url = f"{self.store_list_url}?lat={user_lat}&lng={user_lng}"
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        
        # Indiranagar Hub kareeb hona chahiye
        self.assertEqual(response.data[0]['name'], 'Indiranagar Hub')
        self.assertEqual(response.data[1]['name'], 'Koramangala Hub')


# ======================================================
# NAYA TEST CLASS: REVIEW FEATURE KE LIYE
# ======================================================
class ReviewAPITests(APITestCase):

    def setUp(self):
        # User 1: Jisne product khareeda hai
        self.user_buyer = User.objects.create_user(username='buyer', phone_number='+91111', password='p1')
        # User 2: Jisne product nahi khareeda
        self.user_non_buyer = User.objects.create_user(username='nonbuyer', phone_number='+91222', password='p2')
        
        self.store = Store.objects.create(name='Test Store')
        self.address = Address.objects.create(user=self.user_buyer, city='Test', full_address='123', pincode='111')
        
        cat = Category.objects.create(name='Test Cat', slug='test-cat')
        self.product = Product.objects.create(name='Test Product', category=cat)
        var = ProductVariant.objects.create(product=self.product, variant_name='1kg', sku='T1')
        
        inv = StoreInventory.objects.create(store=self.store, variant=var, price=100, stock_quantity=10)

        # Ek order banayein jo 'DELIVERED' ho
        self.delivered_order = Order.objects.create(
            user=self.user_buyer,
            store=self.store,
            delivery_address=self.address,
            status=Order.OrderStatus.DELIVERED, # DELIVERED
            payment_status=Order.PaymentStatus.SUCCESSFUL,
            final_total=100
        )
        OrderItem.objects.create(
            order=self.delivered_order,
            inventory_item=inv,
            product_name=self.product.name,
            variant_name=var.variant_name,
            price_at_order=100,
            quantity=1
        )
        
        # Ek review pehle se create karein (list test karne ke liye)
        self.review = Review.objects.create(
            product=self.product,
            user=self.user_buyer,
            rating=5,
            comment="Great product!"
        )
        
        self.review_url = reverse('product-review-list-create', kwargs={'product_id': self.product.id})

    def test_list_reviews(self):
        """Test karein ki koi bhi (even unauthenticated) reviews list dekh sakta hai."""
        response = self.client.get(self.review_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['comment'], "Great product!")
        self.assertEqual(response.data[0]['rating'], 5)

    def test_create_review_fail_not_authenticated(self):
        """Test karein ki unauthenticated user review nahi de sakta."""
        # client logged out hai
        data = {'rating': 4, 'comment': 'Trying to review'}
        response = self.client.post(self.review_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_review_fail_has_not_purchased(self):
        """Test karein ki jisne product nahi khareeda, woh review nahi de sakta."""
        self.client.force_authenticate(user=self.user_non_buyer) # Non-buyer se login karein
        
        data = {'rating': 4, 'comment': 'I did not buy this'}
        response = self.client.post(self.review_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('You must purchase this product', str(response.data['detail']))

    def test_create_review_fail_already_reviewed(self):
        """Test karein ki ek user doosri baar review nahi de sakta."""
        self.client.force_authenticate(user=self.user_buyer) # Buyer se login karein
        
        # Buyer pehle hi setUp mein review de chuka hai
        data = {'rating': 1, 'comment': 'Trying to review again'}
        response = self.client.post(self.review_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('You have already reviewed this product', str(response.data['non_field_errors']))

    def test_create_review_success_and_rating_update(self):
        """
        Test karein ki naya buyer (jisne khareeda hai) review de sakta hai
        aur Product ki average rating update hoti hai.
        """
        # Ek naya buyer banayein
        user_buyer_2 = User.objects.create_user(username='buyer2', phone_number='+91333', password='p3')
        delivered_order_2 = Order.objects.create(
            user=user_buyer_2,
            store=self.store,
            delivery_address=self.address,
            status=Order.OrderStatus.DELIVERED,
            final_total=100
        )
        OrderItem.objects.create(
            order=delivered_order_2,
            inventory_item=OrderItem.objects.first().inventory_item, # Same item
            price_at_order=100,
            quantity=1
        )
        
        # Check karein ki abhi Product par 1 review hai (rating 5)
        self.product.refresh_from_db()
        self.assertEqual(self.product.review_count, 1)
        self.assertEqual(self.product.average_rating, Decimal('5.00'))
        
        # Naye buyer se login karein
        self.client.force_authenticate(user=user_buyer_2)
        data = {'rating': 3, 'comment': 'It was okay.'}
        response = self.client.post(self.review_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Review.objects.count(), 2)
        
        # Check karein ki Product ki rating update hui
        self.product.refresh_from_db()
        self.assertEqual(self.product.review_count, 2)
        # Avg = (5 + 3) / 2 = 4.00
        self.assertEqual(self.product.average_rating, Decimal('4.00'))