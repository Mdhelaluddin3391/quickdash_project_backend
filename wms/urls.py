# wms/urls.py
from django.urls import path
from .views import (
    ReceiveStockView,
    PickerTaskListView,
    PickTaskCompleteView
)

urlpatterns = [
    # Admin/Manager API
    path('receive-stock/', 
         ReceiveStockView.as_view(), 
         name='wms-receive-stock'),

    # Picker Mobile App APIs
    path('my-pick-tasks/', 
         PickerTaskListView.as_view(), 
         name='wms-picker-tasks'),
    path('pick-tasks/<int:pk>/complete/', 
         PickTaskCompleteView.as_view(), 
         name='wms-complete-task'),
]