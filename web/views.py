from django.views.generic import TemplateView

# Har template page ke liye ek simple View banate hain
# Taki hum unpar link kar sakein

class IndexView(TemplateView):
    template_name = "index.html"

class AuthView(TemplateView):
    template_name = "auth.html"

class CartView(TemplateView):
    template_name = "cart.html"

class CategoryView(TemplateView):
    template_name = "category.html"

class CategoryDetailView(TemplateView):
    # Note: Ise dynamic data ke liye baad mein badalna hoga
    template_name = "category_detail.html"

class CheckoutView(TemplateView):
    template_name = "checkout.html"

class ProductView(TemplateView):
    # Note: Ise dynamic data ke liye baad mein badalna hoga
    template_name = "product.html"

class ProfileView(TemplateView):
    template_name = "profile.html"

class SearchResultsView(TemplateView):
    template_name = "search_results.html"

class OrderSuccessView(TemplateView):
    template_name = "order_success.html"