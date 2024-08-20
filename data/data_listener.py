import redis
from dotenv import dotenv_values 
import config
from pathlib import Path
import json
import time

r = redis.Redis(**config.get_redis_host_and_port())
pair = "MATICMYR"
prices_path = f"./data/prices/prices_{pair}.json"
trades_path = f"./data/trades/trades_{pair}.json"
redis_channels_sub = [f"TRADES::{pair}", f"LOB::{pair}"]

pubsub = r.pubsub()
pubsub.subscribe(*redis_channels_sub)
write_time = int(time.time()*1000)
write_freq = 1000
for message in pubsub.listen():
    if message['type'] == 'message':
        if message['channel'] == b'LOB::MATICMYR':
            now = int(time.time()*1000)
            if now - write_time > write_freq:
                """write to file every second"""
                write_time = now
                with open(Path(prices_path), 'a') as f:
                    json.dump(json.loads(message['data']),f)
                    f.write(',\n')
        if message['channel'] == b'TRADES::MATICMYR':
            with open(Path(trades_path), 'a') as f:
                json.dump(json.loads(message['data']),f)
                f.write(',\n')