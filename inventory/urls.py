from django.urls import path
from .views import StoreInventoryListView, StoreInventoryDetailView
from .views import StoreInventoryListView, StoreInventoryDetailView, ProductSearchView, StaffInventoryUpdateView

urlpatterns = [

    path('store/<int:store_id>/products/', 
         StoreInventoryListView.as_view(), 
         name='store-product-list'),

    path('item/<int:pk>/', 
         StoreInventoryDetailView.as_view(), 
         name='inventory-item-detail'),


     path('search/', 
         ProductSearchView.as_view(), 
         name='product-search'),

    path('staff/item/<int:pk>/update/',
         StaffInventoryUpdateView.as_view(),
         name='staff-inventory-update'),
]