import uuid
from redis.asyncio import Redis

class RedisDistributedLock:
    def __init__(self, redis_client: Redis, key: str, ttl: int = 5):
        self.redis = redis_client
        self.key = f"lock:{key}"  # lock name (e.g., lock:auction:1)
        self.ttl = ttl            # lock TTL (seconds) - prevents deadlocks
        self.token = str(uuid.uuid4())  # unique token to verify lock ownership

    # Executed when entering 'async with'
    async def __aenter__(self):
        # SET key value NX (Only if Not eXists) EX (Expire)
        # In other words, "set only if key does not exist" = try to acquire the lock
        acquired = await self.redis.set(self.key, self.token, nx=True, ex=self.ttl)
        return acquired

    # Executed when exiting 'async with'
    async def __aexit__(self, exc_type, exc_value, traceback):
        # Release the lock only if the current value (token) matches ours (Lua script)
        # This prevents accidentally deleting a lock acquired by someone else
        # in case our lock expired and another client acquired it.
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await self.redis.eval(lua_script, 1, self.key, self.token)