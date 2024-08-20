# Market Making

This repo runs a simple market making bot on Luno.

## Avellaneda & Stoikov Market Making

Reservation price $r(s,t) = s-q\gamma \sigma^2(T-t)$

Spread $\delta^a + \delta^b = \gamma\sigma^2 (T-t) +ln(1+\frac{\gamma}{\kappa})$

Order sizing:

$\phi^{bid}_t = \phi^{max}_t \exp (-\eta q_t) \text{if } q_t>0$

$\phi^{ask}_t = \phi^{max}_t \exp (\eta q_t) \text{if } q_t<0$

Order size is first quantized to the right size allowed by the exchange, and then floor at min order size allowed.
Price size is also quantized to the right tick size allowed by the exchange.

### Market Variables
Volatility $\sigma$ time window is a variable defined and calculated upfront in orderbook. It is currently calculated using VAMP or any fair price methodology that you prefer.

$\kappa$ is modeled based on all trade data (market depth $\delta$ vs execution size) of a given lookback window (this is also defined in orderbook).

$\lambda (\delta) = Aexp(-\kappa \delta)$

## Set Up

### Redis
Run Redis on Docker with the following configs. 

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
`python marketmaking/avellaneda.py`

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