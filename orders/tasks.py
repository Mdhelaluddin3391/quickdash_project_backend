# orders/tasks.py

import logging # <-- ADD
from celery import shared_task
from django.conf import settings
import razorpay
from .models import Order, Payment
from razorpay.errors import BadRequestError, ServerError
from celery.exceptions import Retry
# Import karein taaki Celery retries sahi se kaam karein
# import razorpay # <-- REMOVED (Duplicate)
# from celery.exceptions import Retry # <-- REMOVED (Duplicate)

# Setup logger
logger = logging.getLogger(__name__) # <-- ADD

@shared_task(
    bind=True, 
    autoretry_for=(BadRequestError, ServerError, Retry), # Razorpay ya network error par retry karega
    retry_backoff=True, # Har retry mein zyada der wait karega
    max_retries=3       # Max 3 baar retry karega
)
def process_razorpay_refund_task(self, payment_id, amount_to_refund_paise=None, is_partial_refund=False):
    """
    --- UPDATED ---
    Ek background task jo Razorpay payment ko refund karta hai.
    Yeh ab 'amount_to_refund_paise' (partial refund ke liye) aur 
    'is_partial_refund' flags ko support karta hai.
    """
    try:
        payment = Payment.objects.get(id=payment_id)
    except Payment.DoesNotExist:
        logger.error(f"Refund Task ERROR: Payment ID {payment_id} nahi mila. Task stop kar raha hoon.") # <-- CHANGED
        return f"Payment {payment_id} not found."

    order = payment.order
    
    # --- NAYA LOGIC ---
    if amount_to_refund_paise is None:
        # Full refund (default behavior)
        refund_amount_paise = int(payment.amount * 100)
    else:
        # Partial refund (new behavior)
        refund_amount_paise = amount_to_refund_paise
    
    if refund_amount_paise <= 0:
        logger.info(f"Refund Task INFO: Amount to refund is zero or less for Payment {payment_id}. Skipping.") # <-- CHANGED
        return "Amount is zero."
    # --- END NAYA LOGIC ---

    # Agar refund pehle hi ho chuka hai (sirf full refund ke liye check karein)
    if not is_partial_refund and payment.status == Order.PaymentStatus.REFUNDED:
        logger.info(f"Refund Task INFO: Payment {payment_id} pehle hi 'REFUNDED' hai.") # <-- CHANGED
        return "Already refunded."
        
    # Agar status INITIATED nahi hai (sirf full refund ke liye check karein)
    if not is_partial_refund and payment.status != Order.PaymentStatus.REFUND_INITIATED:
        logger.error(f"Refund Task ERROR: Payment {payment_id} ka status 'REFUND_INITIATED' nahi hai.") # <-- CHANGED
        return f"Payment status is not {Order.PaymentStatus.REFUND_INITIATED}."

    try:
        logger.info(f"Refund Task: Razorpay refund shuru kar raha hoon (Payment ID: {payment.transaction_id})...") # <-- CHANGED
        
        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        
        # Refund API call
        refund_response = client.payment.refund(
            payment.transaction_id, 
            {'amount': refund_amount_paise}
        )
        
        if refund_response and refund_response.get('status') == 'processed':
            
            # --- NAYA LOGIC ---
            if not is_partial_refund:
                # Full refund: Poora status update karein
                payment.status = Order.PaymentStatus.REFUNDED
                payment.save(update_fields=['status'])
                order.payment_status = Order.PaymentStatus.REFUNDED
                order.save(update_fields=['payment_status'])
                logger.info(f"Refund Task SUCCESS: Order {order.order_id} (Full) successfully refund ho gaya.") # <-- CHANGED
            else:
                # Partial refund: Sirf log karein, status change na karein
                logger.info(f"Refund Task SUCCESS: Order {order.order_id} (Partial) of {refund_amount_paise} paise successfully refund ho gaya.") # <-- CHANGED
            # --- END NAYA LOGIC ---
            
            return f"Refund successful for Order {order.order_id}"
        else:
            logger.warning(f"Refund Task WARNING: Refund for {order.order_id} ka status '{refund_response.get('status')}' hai. Dobara try karein...") # <-- CHANGED
            raise Retry(exc=Exception(f"Refund status was: {refund_response.get('status')}"))

    except BadRequestError as e: # 'RazorpayError' ko 'BadRequestError' se replace karein (zyada specific)
        error_code = e.args[0].get('code') if e.args[0] else None
        if error_code == 'BAD_REQUEST_ERROR' and "already been refunded" in str(e):
            logger.info(f"Refund Task INFO: Payment {payment.id} pehle hi refund ho chuka hai (API se pata chala).") # <-- CHANGED
            if not is_partial_refund:
                payment.status = Order.PaymentStatus.REFUNDED
                payment.save(update_fields=['status'])
                order.payment_status = Order.PaymentStatus.REFUNDED
                order.save(update_fields=['payment_status'])
            return "Payment was already refunded."
        
        logger.error(f"Refund Task ERROR (BadRequestError) for Order {order.order_id}: {e}") # <-- CHANGED
        raise self.retry(exc=e)
        
    except Exception as e:
        logger.error(f"Refund Task ERROR (General) for Order {order.order_id}: {e}") # <-- CHANGED
        raise self.retry(exc=e)