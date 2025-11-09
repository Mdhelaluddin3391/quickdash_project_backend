# orders/tasks.py

from celery import shared_task
from django.conf import settings
import razorpay
from .models import Order, Payment
from razorpay.errors import BadRequestError, ServerError
from celery.exceptions import Retry
# Import karein taaki Celery retries sahi se kaam karein
import razorpay
from celery.exceptions import Retry

@shared_task(
    bind=True, 
    autoretry_for=(BadRequestError, ServerError, Retry), # Razorpay ya network error par retry karega
    retry_backoff=True, # Har retry mein zyada der wait karega
    max_retries=3       # Max 3 baar retry karega
)
def process_razorpay_refund_task(self, payment_id):
    """
    Ek background task jo Razorpay payment ko refund karta hai.
    """
    try:
        payment = Payment.objects.get(id=payment_id)
    except Payment.DoesNotExist:
        print(f"Refund Task ERROR: Payment ID {payment_id} nahi mila. Task stop kar raha hoon.")
        return f"Payment {payment_id} not found."

    # Agar refund pehle hi ho chuka hai, toh kuch na karein
    if payment.status == Order.PaymentStatus.REFUNDED:
        print(f"Refund Task INFO: Payment {payment_id} pehle hi 'REFUNDED' hai.")
        return "Already refunded."
        
    # Agar status INITIATED nahi hai (galti se call hua), toh stop karein
    if payment.status != Order.PaymentStatus.REFUND_INITIATED:
        print(f"Refund Task ERROR: Payment {payment_id} ka status 'REFUND_INITIATED' nahi hai.")
        return f"Payment status is not {Order.PaymentStatus.REFUND_INITIATED}."

    order = payment.order
    
    try:
        print(f"Refund Task: Razorpay refund shuru kar raha hoon (Payment ID: {payment.transaction_id})...")
        
        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        
        refund_amount_paise = int(payment.amount * 100)
        
        # Refund API call
        refund_response = client.payment.refund(
            payment.transaction_id, 
            {'amount': refund_amount_paise}
        )
        
        if refund_response and refund_response.get('status') == 'processed':
            # Yeh sabse zaroori hai: Payment aur Order ko 'REFUNDED' mark karein
            payment.status = Order.PaymentStatus.REFUNDED
            payment.save(update_fields=['status'])
            
            order.payment_status = Order.PaymentStatus.REFUNDED
            order.save(update_fields=['payment_status'])
            
            print(f"Refund Task SUCCESS: Order {order.order_id} (Payment ID: {payment.id}) successfully refund ho gaya.")
            return f"Refund successful for Order {order.order_id}"
        else:
            # Refund create hua but 'processed' nahi (e.g., 'pending')
            print(f"Refund Task WARNING: Refund for {order.order_id} ka status '{refund_response.get('status')}' hai. Dobara try karein...")
            # Task ko retry ke liye raise karein
            raise Retry(exc=Exception(f"Refund status was: {refund_response.get('status')}"))

    except RazorpayError as e:
        # Agar Razorpay se error aaye (e.g., "Payment already refunded")
        error_code = e.args[0].get('code')
        if error_code == 'BAD_REQUEST_ERROR' and "already been refunded" in str(e):
            print(f"Refund Task INFO: Payment {payment.id} pehle hi refund ho chuka hai (API se pata chala).")
            # Hum isse successful maankar status update kar denge
            payment.status = Order.PaymentStatus.REFUNDED
            payment.save(update_fields=['status'])
            order.payment_status = Order.PaymentStatus.REFUNDED
            order.save(update_fields=['payment_status'])
            return "Payment was already refunded."
        
        print(f"Refund Task ERROR (RazorpayError) for Order {order.order_id}: {e}")
        # Task ko retry ke liye raise karein
        raise self.retry(exc=e)
        
    except Exception as e:
        print(f"Refund Task ERROR (General) for Order {order.order_id}: {e}")
        # Task ko retry ke liye raise karein
        raise self.retry(exc=e)