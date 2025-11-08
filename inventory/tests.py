from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from store.models import Category, Product, ProductVariant, Store
from inventory.models import StoreInventory
from django.contrib.gis.geos import Point
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.gis.geos import Point 
from store.models import Category, Product, ProductVariant, Store

class InventoryAPITests(APITestCase):

    def setUp(self):
        self.store1 = Store.objects.create(name='Store 1', location=Point(77.0, 12.0))
        self.store2 = Store.objects.create(name='Store 2', location=Point(77.1, 12.1))
        
        cat = Category.objects.create(name='Dairy', slug='dairy')
        prod = Product.objects.create(name='Milk', category=cat)
        
        self.variant1 = ProductVariant.objects.create(product=prod, variant_name='500ml', sku='M1')
        self.variant2 = ProductVariant.objects.create(product=prod, variant_name='1L', sku='M2')

        self.inv1 = StoreInventory.objects.create(
            store=self.store1, 
            variant=self.variant1, 
            price=25, 
            stock_quantity=10
        )
        self.inv2 = StoreInventory.objects.create(
            store=self.store1, 
            variant=self.variant2, 
            price=50, 
            stock_quantity=5
        )
        
        self.inv3 = StoreInventory.objects.create(
            store=self.store2, 
            variant=self.variant1, 
            price=26, 
            stock_quantity=8
        )
        
        prod_oos = Product.objects.create(name='Cheese', category=cat)
        var_oos = ProductVariant.objects.create(product=prod_oos, variant_name='100g', sku='C1')
        self.inv_oos = StoreInventory.objects.create(
            store=self.store1, 
            variant=var_oos, 
            price=100, 
            stock_quantity=0 
        )

    def test_list_inventory_for_store_1(self):
        """Test karein ki Store 1 ke sirf available products hi list hote hain."""
        url = reverse('store-product-list', kwargs={'store_id': self.store1.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        
        response_skus = {item['variant']['sku'] for item in response.data}
        self.assertIn('M1', response_skus)
        self.assertIn('M2', response_skus)
        self.assertNotIn('C1', response_skus)

    def test_list_inventory_for_store_2(self):
        """Test karein ki Store 2 ka sirf 1 product list hota hai."""
        url = reverse('store-product-list', kwargs={'store_id': self.store2.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['variant']['sku'], 'M1')

    def test_get_inventory_item_detail(self):
        """Test karein ki ek single inventory item ki detail sahi aati hai."""
        url = reverse('inventory-item-detail', kwargs={'pk': self.inv1.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.inv1.id)
        self.assertEqual(response.data['variant']['sku'], 'M1')
        self.assertEqual(float(response.data['current_price']), 25.00)