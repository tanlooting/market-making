""" 
Trading Strategy Framework

Luno Client Reference
https://github.com/luno/luno-python/blob/main/luno_python/client.py
"""

import redis
import config
import json
import yaml
import time
import uuid
import numpy as np
from luno_python.client import Client
from dotenv import dotenv_values
from typing import Union
from termcolor import cprint
from order_tracker import OrderTracker
import sys

class AvellanedaStrategy:
    def __init__(self, 
                 auth_config: dict, 
                 pair: str, 
                 trading_rules: dict,
                 sub_channels:Union[list[str], str], 
                 trading_config: dict,
                 simulated: bool = True) -> None:
        # connect to orderbook or listen to redis channel
        self._auth = {
            "api_key_id": auth_config["LUNO_KEY_ID"],
            "api_key_secret": auth_config["LUNO_KEY_SECRET"],
        }
        self._pair = pair
        self.assets= [self._pair[i:i+3] for i in range(0, len(self._pair), 3)]
        self._base_asset, self._quote_asset = self.assets
        self._trading_rules = trading_rules # specific to Luno only

        # user inputs
        self.order_size = 0.1 # 1 unit to trade
        self.gamma = 1
        self.eta = -0.005 # for order sizing - set to 0 for no change in order size
        self.min_spread = 0
        self.order_refresh_rate_s = 60
        self.filled_order_delay_s = 60 
        self.max_order_age_s = 1800 
        self.update_balance_interval_s = 2
        # self.wait_for_cancel_updates = False # not implemented yet

        self._last_update_balance_time_s = None
        self._redis = redis.Redis(**config.get_redis_host_and_port())
        self._redis_channels_sub = list(sub_channels)
        self.client = Client(**self._auth)
        self.trading_config = trading_config
        self._simulated = simulated
        self.orders_tracker = OrderTracker()
        self.q_target = None
        self.q = None
        self.time_left_fraction = 1 # no market close

        # not implemented yet - for scheduling Bot
        self.start_time = None
        self.end_time = None

        self._initialize()

    def _initialize(self):
        """Update inventory"""
        self.update_balance(print = True)
        if self._simulated:
            cprint("Simulated trading not implemented yet.", "red")
            # sys.exit(1)

    def run(self) -> None:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(*self._redis_channels_sub)
        for msg in pubsub.listen():
            self.on_tick(msg)
    
    def on_tick(self, message: str):
        """Process Strategy here"""
        tick = json.loads(message['data'])

        if tick['buffer_ready'] == "False":
            return
        
        vol = float(tick['volatility'])
        mid_price = float(tick['mid_price'])
        vamp = float(tick['vamp']) # unused for now
        best_ask = float(tick['best_ask'])
        best_bid = float(tick['best_bid'])
        alpha = float(tick['alpha'])
        kappa = float(tick['kappa'])
        
        # update balance every update_balance_interval_s
        if time.time() - self._last_update_balance_time_s > self.update_balance_interval_s:
            self.update_balance()
        
        # update inventory calculation
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

        if (np.isnan(alpha) and np.isnan(kappa)) or kappa == 0:
            return

        r_price = mid_price - self.q * self.gamma * vol * self.time_left_fraction
        opt_spread = self.gamma * vol * self.time_left_fraction + 2 * np.log(1+self.gamma / kappa)/self.gamma
        
        ask_quote = self._quantize_price(r_price + opt_spread/2)
        bid_quote = self._quantize_price(r_price - opt_spread/2)
        ask_size = self.order_size if self.q > 0 else self.order_size * np.exp(self.eta * self.q)
        bid_size = self.order_size if self.q < 0 else self.order_size * np.exp(-self.eta * self.q)
        ask_size = max(self._trading_rules['min_order_size'], self._quantize_size(ask_size))
        bid_size = max(self._trading_rules['min_order_size'], self._quantize_size(bid_size))
        
        if self._simulated:
            # TODO: print values only for now
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
            return
        else:
            # WARNING: ACTUAL TRADING
            if self.orders_tracker.last_order_time is None:
                # no last order time, place new order
                self.place_limit_order(ask_quote, ask_size, 'ASK', post_only=True)
                self.place_limit_order(bid_quote, bid_size, 'BID', post_only=True)
            
            elif self.orders_tracker.last_order_time + self.order_refresh_rate_s*1000 > int(time.time()*1000):
                # cancel all order and enter new orders
                self.flat_all()
                # if one sided is filled, q changes so new limit orders will be adjusted accordingly
                self.place_limit_order(ask_quote, ask_size, 'ASK', post_only=True)
                self.place_limit_order(bid_quote, bid_size, 'BID', post_only=True)
            else: # don't do anything if order is still fresh
                return

    def update_balance(self, print = False):
        self.balances = self.client.get_balances(self.assets)['balance']
        self.inventory = {i['asset']: float(i['balance']) for i in self.balances}
        self._last_update_balance_time_s = time.time()  # update balance time
        if print:
            cprint(self.inventory, "red")
  
    def on_user_stream_update(self, message: str):
        # TODO: if cancel or fill event, do something here
        raise NotImplementedError("User stream update handler not implemented yet.")
        # self.on_cancel(message)
        # self.on_fill(message)
    
    def place_limit_order(self, 
                          price: float, 
                          volume: float, 
                          side: str, 
                          post_only: bool = True):
        """ Place limit order on Luno 
        Args:
            price (float): Price of the order
            volume (float): Volume of the order
            side (str): 'BID' or 'ASK'
            post_only (bool): If True, the order will only be placed if it passes all applicable post-only checks.
        """
        oid = str(uuid.uuid4())
        self.orders_tracker.add_orders(oid, side)
        if self._simulated:
            return
        else:
            self.client.post_limit_order(
                pair = self._pair,
                price = price,
                type = side,
                volume = volume,
                client_order_id = oid,
                post_only = post_only
            )

    def cancel_order(self, order_id):
        self.client.stop_order(order_id)
        self.orders_tracker.cancel_order(order_id)
    
    def flat_all(self):
        for oid in self.orders_tracker.active_orders:
            self.cancel_order(oid)

    def _quantize_size(self, amount):
        """Quantize order size to minimum size"""
        return (amount // self._trading_rules['order_size_quantum']) * self._trading_rules['order_size_quantum']

    def _quantize_price(self, price):
        """Quantize order price to tick size"""
        return (price // self._trading_rules['price_quantum']) * self._trading_rules['price_quantum']
    
if __name__ == "__main__":
    auth_config = dotenv_values(".env")

    with open('./limit_order_book/symbols.yaml', 'r') as f:
        all_trading_rules = yaml.safe_load(f)
    
    pair = "MATICMYR"
    
    trading_rules = dict(
        min_order_size = all_trading_rules['min_order_size'][pair],
        order_size_quantum = all_trading_rules['order_size_quantum'][pair],
        price_quantum = all_trading_rules['price_quantum'][pair],
    )

    AvellanedaStrategy(auth_config = auth_config, 
                    pair = "MATICMYR", 
                    trading_rules= trading_rules,
                    sub_channels = ["LOB::XBTMYR"], 
                    trading_config = None).run()
    