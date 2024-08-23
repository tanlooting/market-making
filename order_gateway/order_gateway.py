"""
Luno Order Gateway
https://www.luno.com/en/developers/api#tag/Streaming-API 

3 types of events: order_status, order_fill, balance_update 
The server keeps a cache of all messages sent in the last 5 minutes. 
When reconnecting, messages generated while the client was disconnected 
will be resent to ensure messages are not missed. 
Note that staying disconnected 
for longer than 5 minutes will discard the message cache.

"""

import time
import json
import config
import redis
import asyncio
import datetime
from dotenv import dotenv_values 
from websockets.client import connect as websocket_connect

class BackOffException(Exception):
    pass
        
class LunoUserStream:
    """ Luno Exchange Order Manager

    Manages user stream events and new outgoing messages from trading system.
    """
    def __init__(self, auth_config: dict):

        self.__auth = {
            "api_key_id": auth_config["LUNO_KEY_ID"],
            "api_key_secret": auth_config["LUNO_KEY_SECRET"],
        }
        self._websocket = None
        self._time_last_connection_attempt = None
        self._url = "wss://ws.luno.com/api/1/userstream"
        # base
        self._redis = redis.Redis(**config.get_redis_host_and_port())
        self._order_updates_channel = "ORDER_UPDATES"
    
    def check_backoff(self):
        if self._time_last_connection_attempt is not None:
            delta = time.time() - self._time_last_connection_attempt
            if delta < 10:
                raise BackOffException()
    
    async def connect(self):
        if self._websocket is not None:
            await self._websocket.close()
        try: 
            self.check_backoff()
        except BackOffException:
            await asyncio.sleep(10)
        
        self._time_last_connection_attempt = time.time()
        
        self._websocket = await websocket_connect(self._url, max_size=2**21)

        await self._websocket.send(json.dumps(self.__auth))
 
    async def run(self):
        """Start user stream (statuses/ fills)"""
        await self.connect()

        async for message in self._websocket:
            if message == '""':
                continue

            processed_dict = await self.handle_order_event(json.loads(message))
            if processed_dict is not None:
                await self._redis.publish(self._order_updates_channel, 
                                          json.dumps(processed_dict))
    

    async def handle_order_event(self, msg: dict) -> dict:
        """Handle status updates or fill updates
        
        Order_event:{
            'type': 'order_status' or 'order_fill'
            'order_status_update':,
            'order_fill_update':,
        }
        """
        processed_update = None
        if msg['type'] == 'order_status':
            processed_update = self.order_status_handler(msg['order_status_update'])
            return processed_update 
        elif msg['type'] == 'order_fill':
            processed_update = self.order_fill_handler(msg['order_fill_update'])
        elif msg['type'] == 'balance_update':
            processed_update = self.balance_update_handler(msg['balance_update'])
        return processed_update 
        
    
    @staticmethod
    def order_status_handler(msg: dict) -> dict:
        """Translate Order status message for trading system
        
        Sample message
        {
            'order_id': 'BXBWD2YQMEEBBXS', 
            'client_order_id': '', 
            'market_id': 'ETHMYR', 
            'status': 'PENDING'
        }

        Translated message
        {
            'order_id': '', 
            'exchange_order_id': 'BXBWD2YQMEEBBXS',
            'full_symbol': 'ETHMYR LUNO'
            'symbol': 'ETHMYR', 
            'exchange': 'LUNO',
            'status': 'PENDING'
        }
        """
        return dict(
                msg_type = "ORDER_STATUS",
                order_id = msg['client_order_id'],
                exchange_order_id = msg['order_id'],
                full_symbol = f"{msg['market_id']} LUNO",
                symbol = msg['market_id'],
                exchange = "LUNO",
                order_status = msg['status'],
            )
        
        
    @staticmethod
    def order_fill_handler(msg: dict) -> dict:
        """Translate Order status message for trading system
        
        Sample message
        Currency pair: ETH (Base), MYR (Counter)
        Buying MYR12 worth of ETHMYR at limit price MYR 11,967
        equivalent to 0.001 ETH
        {
            'order_id': 'BXKBUG8DUMVYCS', 
            'client_order_id': '', 
            'market_id': 'ETHMYR', 
            'base_fill': '0.00100000', 
            'counter_fill': '11.9670000000000000', 
            'base_delta': '0.00100000', 
            'counter_delta': '11.9670000000000000', 
            'base_fee': '0.00000350', 
            'counter_fee': '0', 
            'base_fee_delta': '0.00000350', 
            'counter_fee_delta': '0'}

        Translated message:
        {
            'order_id': '',
            'exchange_order_id': 'BXKBUG8DUMVYCS', 
            'symbol': 'ETHMYR', 
            'exchange': 'LUNO',
            'fill_price': '11967',  (price of the symbol by default)
            'fill_size': '0.001' (base currency by default)
            'commission': '0.00000350',  (base currency by default)
        }
        """

        return dict(
            msg_type = "FILL",
            order_id = msg['client_order_id'],
            exchange_order_id = msg['order_id'],
            full_symbol = f"{msg['market_id']} LUNO",
            symbol = msg['market_id'],
            exchange = "LUNO",
            fill_price = float(msg['counter_fill'])/ float(msg['base_fill']),
            fill_size = float(msg['base_fill']),
            fill_time = datetime.datetime.now(),
            commission = msg['base_fee']
        )

    @staticmethod
    def balance_update_handler(msg: dict) -> dict:
        """ Not implemented yet
        balance_update
        {
        "account_id": 8203463422864003664",
        "row_index": 1,
        "balance": "100.00000000",
        "balance_delta": "100.00000000",
        "available": "99.00000000",
        "available_delta": "1.00000000"
        }
        """
        return msg
    

if __name__ == "__main__":

    auth_config = dotenv_values(".env")
    us = LunoUserStream(auth_config)
    asyncio.run(us.run())