from django.urls import path
from .views import CategoryListView, StoreListView
from .views import CategoryListView, StoreListView, NearestStoreView, ReviewListCreateView, HomePageDataView


urlpatterns = [
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('stores/', StoreListView.as_view(), name='store-list'),
    path('nearest/', NearestStoreView.as_view(), name='nearest-store'), # Naya URL
    path(
        'products/<int:product_id>/reviews/', 
        ReviewListCreateView.as_view(), 
        name='product-review-list-create'
    ),
    path('home-data/', HomePageDataView.as_view(), name='home-page-data'),

]