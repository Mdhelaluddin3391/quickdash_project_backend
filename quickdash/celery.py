# quickdash_project_backend/quickdash/celery.py

import os
from celery import Celery
from celery.schedules import crontab  # <-- Sirf ek import

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quickdash.settings')

app = Celery('quickdash')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()


app.conf.beat_schedule = {
    # Har minute 'delivery.tasks.retry_unassigned_deliveries' task run karega
    'retry-stuck-orders-every-minute': {
        'task': 'retry_unassigned_deliveries',
        'schedule': crontab(), # Ab yeh kaam karega
    },
}
# --- END NAYA BEAT ---


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')