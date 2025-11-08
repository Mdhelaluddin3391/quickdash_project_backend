# inventory/views.py (Fully Updated)

from rest_framework import generics
from rest_framework.permissions import AllowAny
from .models import StoreInventory
from django.db.models import Q 
from rest_framework.response import Response
from .serializers import StoreInventoryListSerializer, StoreInventorySerializer
from rest_framework import status
from rest_framework import status
# --- STEP 1.1: NAYE IMPORTS ADD KAREIN ---
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from django.db.models import F
# --- END NAYE IMPORTS ---
from rest_framework.permissions import IsAuthenticated
from accounts.permissions import IsStoreStaff
from .serializers import StaffInventoryUpdateSerializer # Hamara naya serializer
# --- END NAYE IMPORTS ---

class StoreInventoryListView(generics.ListAPIView):
    """
    API endpoint: /api/inventory/store/<store_id>/products/
    (Is view mein koi badlaav nahi hai)
    """
    permission_classes = [AllowAny]
    serializer_class = StoreInventoryListSerializer

    def get_queryset(self):
        store_id = self.kwargs.get('store_id')
        
        queryset = StoreInventory.objects.filter(
            store__id=store_id,
            is_available=True,
            stock_quantity__gt=0
        ).select_related(
            'variant__product__category',
            'store'
        )
        
        category_slug = self.request.query_params.get('category')
        if category_slug:
            queryset = queryset.filter(
                variant__product__category__slug=category_slug
            )
            
        return queryset

class StoreInventoryDetailView(generics.RetrieveAPIView):
    """
    API endpoint: /api/inventory/item/<int:pk>/
    (Is view mein koi badlaav nahi hai)
    """
    permission_classes = [AllowAny]
    queryset = StoreInventory.objects.filter(
        is_available=True
    ).select_related(
        'variant__product__category', 
        'store'
    )
    serializer_class = StoreInventorySerializer


class ProductSearchView(generics.ListAPIView):
    """
    --- UPDATED ---
    API endpoint: /api/inventory/search/?store_id=1&q=milk
    Ek specific store mein products search karne ke liye (Postgres Full-Text Search ke saath).
    """
    permission_classes = [AllowAny]
    serializer_class = StoreInventoryListSerializer

    def get_queryset(self):
        store_id = self.request.query_params.get('store_id')
        query = self.request.query_params.get('q')

        if not store_id or not query:
            return StoreInventory.objects.none()

        # Base filter: Sahi store, available, aur stock mein ho
        base_filters = Q(
            store__id=store_id,
            is_available=True,
            stock_quantity__gt=0
        )

        # --- STEP 1.2: NAYA ADVANCED SEARCH LOGIC ---
        
        # Hum product name (Weight A - zyada important), 
        # brand (Weight B - thoda kam important),
        # aur variant name (Weight A) par search karenge.
        search_vector = SearchVector(
            'variant__product__name', weight='A'
        ) + SearchVector(
            'variant__product__brand', weight='B'
        ) + SearchVector(
            'variant__variant_name', weight='A'
        )
        
        # SearchQuery banayein
        search_query = SearchQuery(query, search_type='websearch') 

        # Query ko filter, annotate (rank) aur order karein
        queryset = StoreInventory.objects.filter(
            base_filters
        ).annotate(
            rank=SearchRank(search_vector, search_query)
        ).filter(
            rank__gte=0.1 # Sirf relevant results (rank > 0.1) dikhayein
        ).order_by(
            '-rank' # Sabse relevant result sabse upar
        ).select_related(
            'variant__product__category'
        ).distinct() # Duplicate results hatayein
        
        return queryset
        # --- END NAYA LOGIC ---

    def list(self, request, *args, **kwargs):
        store_id = request.query_params.get('store_id')
        query = request.query_params.get('q')

        if not store_id:
            return Response(
                {"error": "store_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not query:
             return Response(
                {"error": "q (search query) parameter is required."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        return super().list(request, *args, **kwargs)


# inventory/views.py

# ... (ProductSearchView ke baad)

class StaffInventoryUpdateView(generics.RetrieveUpdateAPIView):
    """
    API: GET, PATCH /api/inventory/staff/item/<pk>/update/
    Store Staff ko unke store ke ek inventory item ko update karne deta hai.
    """
    permission_classes = [IsAuthenticated, IsStoreStaff]
    serializer_class = StaffInventoryUpdateSerializer
    
    def get_queryset(self):
        """
        Yeh function ensure karta hai ki staff sirf apne hi store
        ke items ko access kar sake.
        """
        user = self.request.user
        if hasattr(user, 'store_staff_profile') and user.store_staff_profile.store:
            # Staff ke store se jude sabhi inventory items ko filter karein
            store = user.store_staff_profile.store
            return StoreInventory.objects.filter(store=store).select_related(
                'variant__product'
            )
        
        # Agar staff kisi store se nahi juda hai, toh unhein kuch nahi milega
        return StoreInventory.objects.none()

    def get_object(self):
        """
        Queryset se ek single object nikaalta hai.
        Agar item staff ke store ka nahi hai, toh 404 Not Found error aayega.
        """
        obj = super().get_object()
        return obj

    def update(self, request, *args, **kwargs):
        # Hum 'PUT' (poora update) disable kar rahe hain, sirf 'PATCH' (partial update) allow karenge
        if request.method == 'PUT':
            return Response(
                {"error": "PUT method not allowed. Please use PATCH."},
                status=status.HTTP_405_METHOD_NOT_ALLOWED
            )
        
        # 'partial=True' yeh ensure karta hai ki yeh PATCH request hai
        # Isse staff sirf 'stock_quantity' ya sirf 'price' bhi bhej sakta hai
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(serializer.data)