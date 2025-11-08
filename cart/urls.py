from django.urls import path
from .views import (
    CartDetailView, 
    CartItemAddView, 
    CartItemUpdateView, 
    CartItemRemoveView,
    
)

urlpatterns = [

    path('', CartDetailView.as_view(), name='view-cart'),
    

    path('add/', CartItemAddView.as_view(), name='add-to-cart'),
    
   
    path('item/<int:pk>/update/', 
         CartItemUpdateView.as_view(), 
         name='update-cart-item'),
    

    path('item/<int:pk>/remove/', 
         CartItemRemoveView.as_view(),
         name='remove-cart-item'),
]