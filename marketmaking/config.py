from dotenv import dotenv_values


def get_redis_host_and_port():
    config = dotenv_values(".env")
    host = config["REDIS_HOST"]
    port = config["REDIS_PORT"]
    return dict(host=host, port=port)