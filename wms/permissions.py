# wms/permissions.py
from rest_framework.permissions import BasePermission
from accounts.permissions import IsStoreStaff # Maujooda permission ko import karein

class IsStoreManager(IsStoreStaff):
    """
    Custom permission to only allow Store Staff who are MANAGERS.
    (Design Doc ke mutabik 'is_manager=True')
    """
    message = "Only store managers can perform this action."

    def has_permission(self, request, view):
        # Pehle check karein ki user 'IsStoreStaff' hai ya nahi
        if not super().has_permission(request, view):
            return False

        # Ab check karein ki woh manager hai ya nahi
        return request.user.store_staff_profile.is_manager

class IsStorePicker(IsStoreStaff):
    """
    Custom permission to only allow Store Staff who can PICK ORDERS.
    (Design Doc ke mutabik 'can_pick_orders=True')
    """
    message = "Only authorized pickers can perform this action."

    def has_permission(self, request, view):
        # Pehle check karein ki user 'IsStoreStaff' hai ya nahi
        if not super().has_permission(request, view):
            return False

        # Ab check karein ki woh pick kar sakta hai ya nahi
        return request.user.store_staff_profile.can_pick_orders