# Market Making

This repo runs a simple market making bot on Luno.

## Avellaneda & Stoikov Market Making
<insert theory here>

## Set Up


### Redis
Run Redis on Docker. 

```
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
```

All channels are by default: `LOB::<pairsymbol>` 
User stream channels are `ORDER_UPDATES`

### Run Bash Script
`bash scripts.sh` to start LOB, client order gateway, and trading scripts.

Alternatively, start each services below separately.

### Limit Orderbook (LOB)
Start streaming orderbook 
`python limit_order_book/orderbook.py`

```
auth_config = dotenv_values(".env")
ob = LunoOrderBook(auth_config, "XBTMYR")
asyncio.run(ob.run())
```

### User Stream
Listen to user streams for fill and order status updates.
`python order_gateway/order_gateway.py`

### Market Making Bot
`python marketmaking/trading.py`

#### Listen to redis 
```
self._redis = redis.Redis(**config.get_redis_host_and_port()) 
self._redis_channels_sub = ["LOB::XBTMYR"]

pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
pubsub.subscribe(*self._redis_channels_sub)

for msg in pubsub.listen():
    # processes every tick
    self.on_tick(msg)
```