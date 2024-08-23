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

### User Inputs for Trading
|Params|Default Value|
|---|---|
|order_size | 1|
|risk aversion parameter $\gamma$ | 1 |
|Order Shape Param $\eta$ | -0.005 |
|min_spread |0|
|Waiting time before updating orders: order_refresh_rate_s | 60 |
|filled_order_delay_s | 60| 
|max_order_age_s | 1800| 
|Freq. of updating balance: update_balance_interval_s |2|

### ENV variables
To connect to your Luno account, include the following key_id and key_secret in the `.env` file.
```
LUNO_KEY_ID = ""
LUNO_KEY_SECRET = ""
```

### Redis
Run Redis on Docker with the following configs included in `.env` file. 
```
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
```

All channels are by default: `LOB::<pairsymbol>` 

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

## Not implemented yet

### User Stream
Listen to user streams for fill and order status updates.
`python order_gateway/order_gateway.py`
User stream channels on Redis Stack are `ORDER_UPDATES`