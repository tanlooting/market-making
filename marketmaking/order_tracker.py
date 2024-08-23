from collections import deque
from typing import Optional
import time

class OrderTracker:
    def __init__(self) -> None:
        self._limit_orders = {"BID": deque(), "ASK": deque()}
        self._last_order_time: Optional[int] = None

    def get_bid_orders(self) -> deque:
        return self._limit_orders["BID"]
    
    def get_ask_orders(self) -> deque:
        return self._limit_orders["ASK"]
    @property
    def last_order_time(self):
        """Return the last timestamp when orders are placed"""
        return self._last_order_time
    
    
    @property
    def no_orders_at_bid(self) -> bool:
        if self._limit_orders["BID"]:
            return False
        return True
    
    @property
    def no_orders_at_ask(self) -> bool:
        if self._limit_orders["ASK"]:
            return False
        return True
    
    @property
    def no_orders(self) -> bool:
        return self.no_orders_at_bid and self.no_orders_at_ask
    
    @property
    def active_orders(self):
        return self._limit_orders['BID'] + self._limit_orders['ASK']
    
    def add_orders(self, order_id:str, side: str):
        self._limit_orders[side].append(order_id)
        self._last_order_time = int(time.time()*1000)
    
    def cancel_order(self, order_id:str):
        if order_id in self._limit_orders['BID']:
            self._limit_orders['BID'].remove(order_id)
        elif order_id in self._limit_orders['ASK']:
            self._limit_orders['ASK'].remove(order_id)