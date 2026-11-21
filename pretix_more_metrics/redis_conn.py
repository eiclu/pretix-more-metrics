from django.conf import settings


def get_redis():
    """
    Returns pretix's Redis connection (the ``[redis]`` section of pretix.cfg), or ``None``
    if pretix runs without Redis. Everything that needs Redis is silently disabled then.
    """
    if not settings.HAS_REDIS:
        return None
    import django_redis

    return django_redis.get_redis_connection("redis")
