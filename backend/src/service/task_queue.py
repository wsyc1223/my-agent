import taskiq_redis
from src.config import settings

redis_broker = taskiq_redis.ListQueueBroker(
    url = settings.REDIS_URL
)

import src.eval_service.task
