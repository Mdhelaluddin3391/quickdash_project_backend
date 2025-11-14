from django.urls import path
from . import views

app_name = 'web'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('auth/', views.AuthView.as_view(), name='auth'),
    path('cart/', views.CartView.as_view(), name='cart'),
    path('category/', views.CategoryView.as_view(), name='category'),
    path('checkout/', views.CheckoutView.as_view(), name='checkout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('order-success/', views.OrderSuccessView.as_view(), name='order-success'),
    path('search/', views.SearchResultsView.as_view(), name='search'),
    path('category/<slug:slug>/', views.CategoryDetailView.as_view(), name='category-detail'),
    path('order/<int:pk>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('product/<int:pk>/', views.ProductView.as_view(), name='product-detail'),
    path('location-denied/', views.LocationDeniedView.as_view(), name='location-denied'),
]