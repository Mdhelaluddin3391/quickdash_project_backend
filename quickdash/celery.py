import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quickdash.settings')

app = Celery('quickdash')

app.config_from_object('django.conf:settings', namespace='CELERY')

app.autodiscover_tasks()


app.conf.beat_schedule = {
    # Har minute 'delivery.tasks.retry_unassigned_deliveries' task run karega
    'retry-stuck-orders-every-minute': {
        'task': 'retry_unassigned_deliveries',
        'schedule': crontab(), # crontab() = har minute
    },
}
# --- END NAYA BEAT ---


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')