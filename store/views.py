from rest_framework import generics
from rest_framework.permissions import AllowAny
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from rest_framework.response import Response
from .models import Category, Store
from .serializers import CategorySerializer, StoreSerializer
from rest_framework import status
from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated # <-- IsAuthenticated import karein
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from rest_framework.response import Response
from .models import Category, Store, Product, Review # <-- Product aur Review import karein
from .serializers import CategorySerializer, StoreSerializer, ReviewSerializer # <-- ReviewSerializer import karein
from rest_framework import status
from .permissions import HasPurchasedProduct



class CategoryListView(generics.ListAPIView):
    """
    API endpoint: /api/store/categories/
    Sabhi active categories aur sub-categories ki list return karta hai.
    """
    permission_classes = [AllowAny]
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    # TODO: Future mein, sirf parent categories (parent=None) dikha sakte hain


class StoreListView(generics.ListAPIView):
    """
    API endpoint: /api/store/stores/
    Sabhi active stores ki list return karta hai.
    
    Aap 'lat' aur 'lng' query parameters bhej kar stores ko 
    apni location se doori ke hisaab se sort kar sakte hain.
    e.g., /api/store/stores/?lat=12.9716&lng=77.5946
    """
    permission_classes = [AllowAny]
    serializer_class = StoreSerializer
    
    def get_queryset(self):
        queryset = Store.objects.filter(is_active=True)
        
        latitude = self.request.query_params.get('lat')
        longitude = self.request.query_params.get('lng')

        if latitude and longitude:
            try:
                user_location = Point(float(longitude), float(latitude), srid=4326)

                queryset = queryset.annotate(
                    distance=Distance('location', user_location)
                ).order_by('distance')
                
            except (ValueError, TypeError):
                pass
                
        return queryset


class NearestStoreView(generics.GenericAPIView):
    """
    API endpoint: /api/store/nearest/?lat=...&lng=...
    Customer ki location ke aadhar par sabse kareebi active store
    return karta hai.
    """
    permission_classes = [AllowAny]
    serializer_class = StoreSerializer

    def get(self, request, *args, **kwargs):
        latitude = self.request.query_params.get('lat')
        longitude = self.request.query_params.get('lng')

        if not latitude or not longitude:
            return Response(
                {"error": "lat aur lng query parameters zaroori hain."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user_location = Point(float(longitude), float(latitude), srid=4326)
            
            nearest_store = Store.objects.filter(
                is_active=True,
                location__isnull=False
            ).annotate(
                distance=Distance('location', user_location)
            ).order_by('distance').first() # .first() sirf 1 result dega

            if not nearest_store:
                return Response(
                    {"error": "Aapki location par koi store available nahi hai."},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            serializer = self.get_serializer(nearest_store)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except (ValueError, TypeError):
             return Response(
                {"error": "Invalid lat/lng format."},
                status=status.HTTP_400_BAD_REQUEST
            )

class ReviewListCreateView(generics.ListCreateAPIView):
    """
    API: GET, POST /api/store/products/<product_id>/reviews/
    GET: Ek product ke saare reviews list karta hai.
    POST: Ek product ke liye naya review create karta hai.
    """
    serializer_class = ReviewSerializer
    
    def get_permissions(self):
        """
        GET ke liye sabko permission do (AllowAny),
        POST ke liye custom permission (HasPurchasedProduct) check karo.
        """
        if self.request.method == 'POST':
            return [IsAuthenticated(), HasPurchasedProduct()]
        return [AllowAny()]

    def get_queryset(self):
        # URL se product_id lein
        product_id = self.kwargs.get('product_id')
        # Us product ke saare reviews return karein
        return Review.objects.filter(product_id=product_id).select_related('user')

    def perform_create(self, serializer):
        # Jab review save ho, toh product aur user ko automatically set karein
        product_id = self.kwargs.get('product_id')
        product = Product.objects.get(id=product_id)
        
        serializer.save(
            user=self.request.user,
            product=product
        )