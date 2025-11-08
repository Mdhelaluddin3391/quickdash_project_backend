from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from accounts.models import User
from store.models import Category, Product, ProductVariant, Store
from inventory.models import StoreInventory
from cart.models import Cart, CartItem
from django.contrib.gis.geos import Point

class CartAPITests(APITestCase):

    def setUp(self):
      
        self.user = User.objects.create_user(username='cartuser', phone_number='+91555666777', password='testpass123')
        self.client.force_authenticate(user=self.user)
        self.cart = Cart.objects.create(user=self.user)

        self.store1 = Store.objects.create(name='Store 1', location=Point(77.0, 12.0))
        self.store2 = Store.objects.create(name='Store 2', location=Point(77.1, 12.1))
        
        cat = Category.objects.create(name='Dairy', slug='dairy')
        prod = Product.objects.create(name='Milk', category=cat)
        self.variant1 = ProductVariant.objects.create(product=prod, variant_name='500ml', sku='M1')
        
        self.inv1 = StoreInventory.objects.create(
            store=self.store1, 
            variant=self.variant1, 
            price=30, 
            stock_quantity=5 
        )
        
        self.inv2 = StoreInventory.objects.create(
            store=self.store2, 
            variant=self.variant1, 
            price=30, 
            stock_quantity=10
        )
        
        self.add_url = reverse('add-to-cart')

    def test_add_to_empty_cart(self):
        """Test karein ki khaali cart mein item add hota hai."""
        data = {'inventory_item_id': self.inv1.id, 'quantity': 2}
        response = self.client.post(self.add_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.assertEqual(self.cart.items.count(), 1)
        cart_item = self.cart.items.first()
        self.assertEqual(cart_item.inventory_item, self.inv1)
        self.assertEqual(cart_item.quantity, 2)
        
        self.assertEqual(response.data['item_count'], 1)
        self.assertEqual(float(response.data['total_price']), 60.00)
        self.assertEqual(response.data['store']['id'], self.store1.id) 

    def test_add_to_cart_out_of_stock(self):
        """Test karein ki stock se zyada add karne par error aata hai."""
        data = {'inventory_item_id': self.inv1.id, 'quantity': 6}
        response = self.client.post(self.add_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn('Not enough stock', response.data['error'])
        self.assertEqual(self.cart.items.count(), 0)

    def test_add_to_cart_different_store_fail(self):
        """Test karein ki user do alag-alag store se item add nahi kar sakta."""
        data1 = {'inventory_item_id': self.inv1.id, 'quantity': 1}
        self.client.post(self.add_url, data1)
        
        self.assertEqual(self.cart.store, self.store1)
        
        data2 = {'inventory_item_id': self.inv2.id, 'quantity': 1}
        response = self.client.post(self.add_url, data2)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn(f"Aap sirf '{self.store1.name}' store se hi items add kar sakte hain", response.data['error'])
        self.assertEqual(self.cart.items.count(), 1)

    def test_update_cart_item_quantity(self):
        """Test karein ki cart item ki quantity update hoti hai."""
        cart_item = CartItem.objects.create(cart=self.cart, inventory_item=self.inv1, quantity=1)
        
        update_url = reverse('update-cart-item', kwargs={'pk': cart_item.id})
        data = {'quantity': 3}
        
        response = self.client.patch(update_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        cart_item.refresh_from_db()
        self.assertEqual(cart_item.quantity, 3)
        self.assertEqual(float(response.data['total_price']), 90.00)

    def test_update_cart_item_out_of_stock(self):
        """Test karein ki update karte waqt bhi stock check hota hai."""
        cart_item = CartItem.objects.create(cart=self.cart, inventory_item=self.inv1, quantity=1)
        
        update_url = reverse('update-cart-item', kwargs={'pk': cart_item.id})
        data = {'quantity': 10} 
        
        response = self.client.patch(update_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('error', response.data)
        self.assertIn('Not enough stock', response.data['error'])
        
        cart_item.refresh_from_db()
        self.assertEqual(cart_item.quantity, 1) 

    def test_remove_cart_item_by_update_to_zero(self):
        """Test karein ki quantity 0 update karne par item delete ho jaata hai."""
        cart_item = CartItem.objects.create(cart=self.cart, inventory_item=self.inv1, quantity=2)
        
        update_url = reverse('update-cart-item', kwargs={'pk': cart_item.id})
        data = {'quantity': 0}
        
        response = self.client.patch(update_url, data)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        self.assertEqual(self.cart.items.count(), 0) 
        self.assertFalse(CartItem.objects.filter(id=cart_item.id).exists())

    def test_remove_cart_item_by_delete(self):
        """Test karein ki DELETE request se item remove hota hai."""
        cart_item = CartItem.objects.create(cart=self.cart, inventory_item=self.inv1, quantity=2)
        
        remove_url = reverse('remove-cart-item', kwargs={'pk': cart_item.id})
        response = self.client.delete(remove_url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK) 
        self.assertEqual(self.cart.items.count(), 0)
        self.assertFalse(CartItem.objects.filter(id=cart_item.id).exists())