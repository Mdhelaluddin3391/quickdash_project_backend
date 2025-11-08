from rest_framework.permissions import BasePermission


class IsCustomer(BasePermission):
    """
    Custom permission to only allow users with a CustomerProfile.
    """
    message = "Only customers can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            hasattr(request.user, 'customer_profile') 
        )


class IsRider(BasePermission):
    """
    Custom permission to only allow users with a RiderProfile.
    """
    message = "Only riders can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'rider_profile')
        )

class IsStoreStaff(BasePermission):
    """
    Custom permission to only allow users with a StoreStaffProfile.
    """
    message = "Only store staff can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            hasattr(request.user, 'store_staff_profile') 
        )


