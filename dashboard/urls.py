from django.urls import path
from .views import (
    StaffDashboardView, 
    ManagerOrderListView, 
    CancelOrderItemView,
    ManualPackView,
    CustomerLookupView,
    IssuePickTaskListView,
    ResolveIssueTaskRetryView,
    ResolveIssueTaskCancelView
)

urlpatterns = [
    # /api/dashboard/staff/
    path('staff/', 
         StaffDashboardView.as_view(), 
         name='staff-dashboard'),

    # /api/dashboard/staff/orders/
    path('staff/orders/',
         ManagerOrderListView.as_view(),
         name='staff-order-list'),
         
    # --- NAYA URL (FC) ---
    # /api/dashboard/staff/order-item/cancel/
    path('staff/order-item/cancel/',
         CancelOrderItemView.as_view(),
         name='staff-cancel-item'),
    # --- END NAYA URL ---

    path('staff/order/<str:order_id>/mark-packed/',
         ManualPackView.as_view(),
         name='staff-mark-packed'),


    path('staff/customer-lookup/',
         CustomerLookupView.as_view(),
         name='staff-customer-lookup'),

     path('staff/issue-tasks/',
         IssuePickTaskListView.as_view(),
         name='staff-issue-tasks'),
     
     path('staff/issue-task/<int:pk>/retry/',
         ResolveIssueTaskRetryView.as_view(),
         name='staff-issue-task-retry'),

     path('staff/issue-task/<int:pk>/cancel/',
         ResolveIssueTaskCancelView.as_view(),
         name='staff-issue-task-cancel'),


     
]

