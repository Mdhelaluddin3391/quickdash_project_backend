from django.urls import path
from . import views

# app_name 'web' set karne se hum {% url 'web:index' %} istemal kar payenge
app_name = 'web'

urlpatterns = [
    # Homepage (empty path)
    path('', views.IndexView.as_view(), name='index'),
    
    # Dusre static pages
    path('auth/', views.AuthView.as_view(), name='auth'),
    path('cart/', views.CartView.as_view(), name='cart'),
    path('category/', views.CategoryView.as_view(), name='category'),
    path('checkout/', views.CheckoutView.as_view(), name='checkout'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('order-success/', views.OrderSuccessView.as_view(), name='order-success'),

    # In paths ko baad mein dynamic banana hoga
    path('search/', views.SearchResultsView.as_view(), name='search'),
    path('product/', views.ProductView.as_view(), name='product-detail-static'), 
    path('category-detail/', views.CategoryDetailView.as_view(), name='category-detail-static'),
]