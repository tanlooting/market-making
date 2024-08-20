""" 
Trading Strategy Framework

Luno Client Reference
https://github.com/luno/luno-python/blob/main/luno_python/client.py
"""

import redis
import config
import json
import yaml
import numpy as np
from luno_python.client import Client
from dotenv import dotenv_values
from typing import Union
from termcolor import cprint


class TradingStrategy:
    def __init__(self, 
                 auth_config: dict, 
                 pair: str, 
                 trading_rules: dict,
                 sub_channels:Union[list[str], str], 
                 trading_config: dict) -> None:
        # connect to orderbook or listen to redis channel
        self._auth = {
            "api_key_id": auth_config["LUNO_KEY_ID"],
            "api_key_secret": auth_config["LUNO_KEY_SECRET"],
        }
        self._pair = pair
        self._trading_rules = trading_rules # specific to Luno only
        self._redis = redis.Redis(**config.get_redis_host_and_port())
        self._redis_channels_sub = list(sub_channels)
        self.client = Client(**self._auth)
        self.trading_config = trading_config
        self.bids = list() # list of orderid
        self.asks = list() # list of orderid
        self.trades = list() # TODO: log to file for post-trade analysis
        self.q_target = None
        self.q = None
        self.time_left_fraction = 1 # no market close

        # user inputs
        self.order_size = 1 # 1 unit to trade
        self.gamma = 1
        self.eta = -0.005 # for order sizing
        self.refresh_rate = 60 # seconds
        
        self._setup()

    def _setup(self):
        """
        XBTMYR 
        base asset XBT, quote asset MYR
        """
        assets= [self._pair[i:i+3] for i in range(0, len(self._pair), 3)]
        self._base_asset, self._quote_asset = assets
        self.balances = self.client.get_balances(assets)['balance']
        self.inventory = {i['asset']: float(i['balance']) for i in self.balances}
        cprint(self.inventory, "red")
        

    def run(self) -> None:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(*self._redis_channels_sub)
        # listen to redis
        for msg in pubsub.listen():
            # if message['data'] is fill:
            self.on_fill(msg)
            # elif message['data'] is feed:
            self.on_tick(msg)
    
    def on_tick(self, message: str):
        """Process Strategy here"""
        tick = json.loads(message['data'])
        
        vol = float(tick['volatility'])
        mid_price = float(tick['mid_price'])
        best_ask = float(tick['best_ask'])
        best_bid = float(tick['best_bid'])
        alpha = float(tick['alpha'])
        kappa = float(tick['kappa'])
        
        # XBT in MYR
        self.base_in_quote = self.inventory[self._base_asset] * mid_price
        self.inventory_in_quote = self.base_in_quote + self.inventory[self._quote_asset]
        self.inventory_in_base = self.inventory_in_quote / mid_price
        if self.q_target is None:
            # set to initial q
            self.q_target = self.inventory[self._base_asset]/ self.inventory_in_base
        self.target_inventory_in_quote = self.inventory_in_quote * self.q_target
        self.target_inventory_in_base = self.target_inventory_in_quote / mid_price
        # current inventory q relative to target q
        self.q = (self.inventory[self._base_asset] - self.target_inventory_in_base)/self.inventory_in_base

        if np.isnan(alpha) and np.isnan(kappa):
            return

        r_price = mid_price - self.q * self.gamma * vol * self.time_left_fraction
        opt_spread = self.gamma * vol * self.time_left_fraction + 2 * np.log(1+self.gamma / kappa)/self.gamma
        
        ask_quote = self.quantize_price(r_price + opt_spread/2)
        bid_quote = self.quantize_price(r_price - opt_spread/2)
        ask_size = self.order_size if self.q > 0 else self.order_size * np.exp(self.eta * self.q)
        bid_size = self.order_size if self.q < 0 else self.order_size * np.exp(-self.eta * self.q)
        ask_size = max(self._trading_rules['min_order_size'], self.quantize_size(ask_size))
        bid_size = max(self._trading_rules['min_order_size'], self.quantize_size(bid_size))

        print(dict(
            mid_price=mid_price,
            q = self.q,
            r_price=r_price,
            best_ask=best_ask,
            best_bid=best_bid,
            ask_quote=ask_quote,
            bid_quote=bid_quote,
            ask_size = ask_size,
            bid_size = bid_size,
        ))

    
    def on_fill(self, message: str):
        """from user stream, update execution info"""
        ...
    
    def place_limit_order(self):
        self.client.post_limit_order()

    def place_market_order(self):
        self.client.post_market_order()

    def cancel_order(self, order_id):
        self.client.stop_order(order_id)
    
    def flat_all(self):
        orders = self.client.list_orders()
        # if order still active, cancel it

    def quantize_size(self, amount):
        """Quantize order size to minimum size"""
        return (amount // self._trading_rules['order_size_quantum']) * self._trading_rules['order_size_quantum']

    def quantize_price(self, price):
        """Quantize order price to tick size"""
        return (price // self._trading_rules['price_quantum']) * self._trading_rules['price_quantum']
    
if __name__ == "__main__":
    auth_config = dotenv_values(".env")

    with open('./limit_order_book/symbols.yaml', 'r') as f:
        all_trading_rules = yaml.safe_load(f)
    
    pair = "XBTMYR"
    
    trading_rules = dict(
        min_order_size = all_trading_rules['min_order_size'][pair],
        order_size_quantum = all_trading_rules['order_size_quantum'][pair],
        price_quantum = all_trading_rules['price_quantum'][pair],
    )
    # TradingStrategy(auth_config = auth_config, 
    #                 pair = "XBTMYR", 
    #                 trading_rules= trading_rules,
    #                 sub_channels = ["LOB::XBTMYR"], 
    #                 trading_config = None).run()