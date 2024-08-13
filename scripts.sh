#! /bin/bash

python limit_order_book/orderbook.py --symbol XBTMYR &
python order_gateway/order_gateway.py &
python marketmaking/trading.py &