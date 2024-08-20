"""
Orderbook construction
rate limit: 50 session at one time.
- save market orders.

Reference:
https://github.com/jacoduplessis/luno_streams/blob/master/luno_streams/updater.py
https://github.com/PacktPublishing/Learn-Algorithmic-Trading/blob/master/Chapter7/OrderBook.py
https://www.luno.com/en/developers/api#tag/Streaming-API
"""

import websockets
import asyncio
import json
import time
import yaml
import redis
import config
import argparse
import pandas as pd
import numpy as np
from dotenv import dotenv_values
from decimal import Decimal
from termcolor import cprint
from collections import defaultdict
from scipy.optimize import curve_fit
from typing import Tuple

class BackOffException(Exception):
    ...

class LunoOrderBook:
    def __init__(self, auth_config: dict, pair: str):
        
        self.pair = pair.upper()
        self.auth = {
            "api_key_id": auth_config["LUNO_KEY_ID"],
            "api_key_secret": auth_config["LUNO_KEY_SECRET"],
        }
        self._redis = redis.Redis(**config.get_redis_host_and_port())

        # buffer
        self.bid_trades = list()
        self.ask_trades = list()
        self.trade_buffer_duration = 10 # mins
        self.trade_buffer_ready = False
        # instantaneous volatility ~0.05% 
        self.vol_buffer_size = 200 # ticks
        self.vol_buffer_ready = False
        self.vol_buffer = list()
        self.vol = np.nan
        self.alpha = np.nan
        self.kappa = np.nan

        self.ws = None
        self.sequence = None
        self.bids = {}
        self.asks = {}
        self.url = f"wss://ws.luno.com/api/1/stream/{self.pair}"
        self.time_last_connection_attempt = None
        self.bid_sorted = None
        self.ask_sorted = None
        self.vamp = 0
        self.mid_price = 0
        self.order_imbalance = 0
        self.start_time = int(time.time()*1000)
        
        

    def check_backoff(self):
        """avoid rate limiting"""
        if self.time_last_connection_attempt is not None:
            delta = time.time() - self.time_last_connection_attempt
            if delta < 10:
                raise BackOffException()

    async def connect(self):
        if self.ws is not None:
            await self.ws.close()
        try:
            self.check_backoff()
        except BackOffException:
            await asyncio.sleep(10)
        self.time_last_connection_attempt = time.time()

        self.ws = await websockets.connect(self.url, ping_interval=1)

        await self.ws.send(json.dumps(self.auth))

        msg = await self.ws.recv()
        initial_msg_data = json.loads(msg)
        self.sequence = int(initial_msg_data["sequence"])

        ## CREATE BID ASK TREES HERE
        self.asks = {
            x["id"]: [Decimal(x["price"]), Decimal(x["volume"])]
            for x in initial_msg_data["asks"]
        }
        self.bids = {
            x["id"]: [Decimal(x["price"]), Decimal(x["volume"])]
            for x in initial_msg_data["bids"]
        }

        cprint("Orderbook received", "blue")

    async def run(self):
        """first msg is always a full order book"""
        await self.connect()
        cprint("Streaming starts","green")

        # async for msg in self.ws:
        while True:
            try:
                msg = await self.ws.recv()
                if msg == '""':
                    continue
                await self.handle_message(msg)
                

                ts = time.time()*1000
                #print(self.print_aggregated_lob())
                self.bid_sorted = self.consolidate(self.bids.values(), reverse=True)
                self.ask_sorted = self.consolidate(self.asks.values())

                if ts > self.start_time + self.trade_buffer_duration*60*1000:
                    if self.ask_trades and self.bid_trades:
                        self.trade_buffer_ready = True
                        self.alpha, self.kappa = self.trading_intensity()
                
                # calculate prices
                self.calc_vamp(levels = 10)
                self.calc_midprice()
                self.calc_spread()
                self.calc_order_imbalance(levels = 10)
                # use vamp for volatility calculation
                self.vol_buffer.append(self.vamp)
                if len(self.vol_buffer) > self.vol_buffer_size:
                    self.vol_buffer.pop(0)
                    self.volatility_buffer_ready = True
                    self.vol = np.sqrt(np.sum(np.square(np.diff(np.array(self.vol_buffer))/np.array(self.vol_buffer)[:-1]*100))/self.vol_buffer_size)
                
                processed_msg = dict(
                    ts=ts,
                    mid_price=str(self.mid_price),
                    spread=str(self.spread),
                    best_bid=str(self.bid_sorted[0][0]),
                    best_ask=str(self.ask_sorted[0][0]),
                    best_bid_size=str(self.bid_sorted[0][1]),
                    best_ask_size=str(self.ask_sorted[0][1]),
                    vamp=str(self.vamp),
                    order_imbalance=str(self.order_imbalance),
                    buffer_ready = str(self.trade_buffer_ready),
                    volatility = str(self.vol), # in pct
                    alpha = str(self.alpha),
                    kappa = str(self.kappa),
                )
                self._redis.publish(f"LOB::{self.pair}", json.dumps(processed_msg))
            except websockets.ConnectionClosedError as e:
                cprint(e, "red")
                await self.connect()
                cprint("Reconnecting...", "green")
                continue

    async def handle_message(self, msg):
        """Call individual handlers depending on order type"""
        data = json.loads(msg)
        new_sequence = int(data["sequence"])
        if new_sequence != self.sequence + 1:
            return await self.connect()

        self.sequence = new_sequence
        self.process_message(data)

    def process_message(self, data):
        if data["delete_update"]:
            self.handle_delete(data)
        if data["create_update"]:
            self.handle_create(data)
        if data["trade_updates"]:
            self.handle_trade(data)

    def handle_create(self, data):
        order = data["create_update"]
        price = Decimal(order["price"])
        volume = Decimal(order["volume"])
        key = order["order_id"]
        book = self.bids if order["type"] == "BID" else self.asks
        book[key] = [price, volume]

    def handle_delete(self, data):
        """delete_update only has an order id key, so still have to traverse entire dict on both side to find"""
        order_id = data["delete_update"]["order_id"]
        try:
            del self.bids[order_id]
        except KeyError:
            pass
        try:
            del self.asks[order_id]
        except KeyError:
            pass
        return

    def handle_trade(self, data):
        """
        list[dict]
        keys: ["base", "counter"," maker_order_id","taker_order_id","order_id"]
        """
        ts = int(time.time()*1000)
        for update in data["trade_updates"]:
            update["price"] = Decimal(update["counter"]) / Decimal(update["base"])
            maker_order_id = update["maker_order_id"]
            if maker_order_id in self.bids:
                # sell orders
                self.update_existing_order(key="bids", update=update)
                msg = {
                    'ts': ts, 
                    'price': float(update['price']), 
                    'amount': float(update['base']),
                    'mid_price': float(self.mid_price),
                    'distance': abs(float(update['price']- self.mid_price))
                    }
                self._redis.publish(f"TRADES::{self.pair}", json.dumps(dict(**msg, bidask="ask")))
            
                self.ask_trades.append(msg)
                if ts - self.trade_buffer_duration*60*1000>self.ask_trades[0]['ts']:
                    self.ask_trades.pop(0)
                cprint(update, "red")
            elif maker_order_id in self.asks:
                # buy orders
                self.update_existing_order(key="asks", update=update)
                msg = {
                    'ts': ts, 
                    'price': float(update['price']), 
                    'amount': float(update['base']),
                    'mid_price': float(self.mid_price),
                    'distance': abs(float(update['price'] - self.mid_price))
                    }
                self._redis.publish(f"TRADES::{self.pair}", json.dumps(dict(**msg, bidask="bid")))
                self.bid_trades.append(msg)

                if ts - self.trade_buffer_duration*60*1000>self.bid_trades[0]['ts']:
                    self.bid_trades.pop(0)
                cprint(update, "green")

    def update_existing_order(self, key:str, update:dict):
        book = getattr(self, key)
        order_id = update["maker_order_id"]
        existing_order = book[order_id]
        existing_volume = existing_order[1]
        new_volume = existing_volume - Decimal(update["base"])
        if new_volume == Decimal("0"):
            del book[order_id]
        else:
            existing_order[1] -= Decimal(update["base"])

    def compute_cdf(self, trades):
        cdf = None
        return cdf
    
    
    def trading_intensity(self) -> Tuple[float, float]:
        """Return alpha and kappa"""
        trades = pd.DataFrame(self.ask_trades + self.bid_trades)
        sorted_trades = (trades.groupby('distance')
                         .agg({'amount':'sum'})
                         .reset_index()
                         .sort_values('distance'))
        print(sorted_trades)
        params = curve_fit(lambda t, a,b: a*np.exp(-b*t), 
                   sorted_trades['distance'].to_list(), 
                   sorted_trades['amount'].to_list(),
                   p0 = (0,0),
                   method = "dogbox", 
                   bounds = ([0,0], [np.inf, np.inf]))

        return params[0][0], params[0][1]

    @staticmethod
    def consolidate(orders, reverse:bool=False):
            price_map = defaultdict(Decimal)
            for order in orders:
                price_map[order[0]] += order[1]
            rounded_list = map(
                lambda x: [round(x[0], ndigits=4), round(x[1], ndigits=4)],
                price_map.items(),
            )

            return sorted(rounded_list, key=lambda a: a[0], reverse=reverse)

    def print_aggregated_lob(self, levels:int = 10) -> pd.DataFrame:
        
        return pd.DataFrame(
            {
                "bids": self.bid_sorted[:levels],
                "asks": self.ask_sorted[:levels],
            }
        )
    
    def calc_vamp(self, levels:int= 10):
        # BIDS
        bid_orders = self.bid_sorted[:levels]
        vwap_b = sum([order[0] * order[1] for order in bid_orders])/sum([order[1] for order in bid_orders])
            
        # ASKS
        ask_orders = self.ask_sorted[:levels]
        vwap_a = sum([order[0] * order[1] for order in ask_orders])/sum([order[1] for order in ask_orders])
           
        self.vamp = (vwap_b + vwap_a)/2
    
    def calc_midprice(self):
        self.mid_price = (self.bid_sorted[0][0] + self.ask_sorted[0][0])/2

    def calc_spread(self):
        self.spread = self.ask_sorted[0][0] - self.bid_sorted[0][0]
        
    def calc_microprice(self):
        raise NotImplementedError("Microprice not implemented")
    
    def calc_order_imbalance(self, levels:int=10):
        """Order imbalance
        Q_b/ (Q_a + Q_b)
        1 -> more likely to buy
        0 -> more likely to sell

        Args:
            levels (int, optional): _description_. Defaults to 10.
        """
        bid_orders = self.bid_sorted[:levels]
        ask_orders = self.ask_sorted[:levels]
        q_b = sum([order[1] for order in bid_orders])
        q_a = sum([order[1] for order in ask_orders])
        self.order_imbalance = q_b/(q_a + q_b)


if __name__ == "__main__":
    # python limit_order_book/orderbook.py -s XBTMYR
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--symbol",type = str, help="Symbol")
    args = parser.parse_args()

    with open('./limit_order_book/symbols.yaml', 'r') as f:
        VALID_SYMBOLS = yaml.safe_load(f)['Supported']

    if args.symbol not in VALID_SYMBOLS:
        raise ValueError(f"Symbol {args.symbol} not supported")
    
    auth_config = dotenv_values(".env")
    
    ob = LunoOrderBook(auth_config, args.symbol)
    asyncio.run(ob.run())
    