""" 
Trading Strategy Framework


Luno Client Reference
https://github.com/luno/luno-python/blob/main/luno_python/client.py
"""

import redis
import config
import json
from luno_python.client import Client
from dotenv import dotenv_values
from typing import Union
from termcolor import cprint

class TradingStrategy:
    def __init__(self, 
                 auth_config: dict, 
                 pair: str, 
                 sub_channels:Union[list[str], str], 
                 trading_config: dict) -> None:
        # connect to orderbook or listen to redis channel
        self._auth = {
            "api_key_id": auth_config["LUNO_KEY_ID"],
            "api_key_secret": auth_config["LUNO_KEY_SECRET"],
        }
        self._pair = pair
        self._redis = redis.Redis(**config.get_redis_host_and_port())
        self._redis_channels_sub = list(sub_channels)
        self.client = Client(**self._auth)
        self.trading_config = trading_config
        self.bids = list() # list of orderid
        self.asks = list() # list of orderid
        self.trades = list() # TODO: log to file for post-trade analysis
        self.inventory_target = dict()
        # self._setup()

    def _setup(self):
        self.balances = self.client.get_balances()['balance']
        cprint(self.balances, "red")

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
        print(json.loads(message['data']))

        # print message 
        # calculate where to place order
    
    def on_fill(self, message: str):
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


if __name__ == "__main__":
    auth_config = dotenv_values(".env")
    TradingStrategy(auth_config = auth_config, 
                    pair = "XBTMYR", 
                    sub_channels = ["LOB::XBTMYR"], 
                    trading_config = None).run()