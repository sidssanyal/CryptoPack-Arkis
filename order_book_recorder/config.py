import os
import logging

import ccxt
import ccxtpro
from ccxtpro.base.exchange import Exchange as ProExchange

logger = logging.getLogger(__name__)

BTC_DEPTHS = [0.04]
ETH_DEPTHS = [0.5]

MARKETS = ["BTC/GBP", "ETH/GBP", "BTC/EUR", "ETH/EUR"]

MARKET_DEPTHS = {
    "BTC/GBP": BTC_DEPTHS,
    "BTC/EUR": BTC_DEPTHS,
    "ETH/GBP": ETH_DEPTHS,
    "ETH/EUR": ETH_DEPTHS,
}

ALERT_THRESHOLD = 0.0018
RETRIGGER_THRESHOLD = 0.0005

TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TELEGRAM_API_KEY = os.environ.get("TELEGRAM_API_KEY")

if os.environ.get("REDIS_HOST"):
    REDIS_CONFIG = {
        "host": os.environ["REDIS_HOST"],
        "port": 6379,
        "retry_on_timeout": True,
        "socket_timeout": 20
    }

    if os.environ.get("REDIS_PASSWORD"):
        REDIS_CONFIG["password"] = os.environ["REDIS_PASSWORD"]

    REDIS_BG_WRITES = True

else:
    REDIS_CONFIG = None

async def setup_exchanges():
    exchanges = {
        "Huobi": ccxtpro.huobi({'enableRateLimit': True}),
        "Kraken": ccxtpro.kraken({'enableRateLimit': True}),
        "FTX": ccxtpro.ftx({'enableRateLimit': True}),
        "Bitfinex": ccxtpro.bitfinex({'enableRateLimit': True}),
        "Bitstamp": ccxtpro.bitstamp({'enableRateLimit': True}),
        "Gemini": ccxt.gemini({'enableRateLimit': True}),
        "Coinbase": ccxtpro.coinbasepro({'enableRateLimit': True}),
        "Exmo": ccxt.exmo({'enableRateLimit': True}),
    }

    for name, xchg in exchanges.items():

        if isinstance(xchg, ProExchange):
            logger.info("Loading markets for %s %s", name, xchg)
            await xchg.load_markets()
        else:
            logger.info("Calling blocking API for %s %s", name, xchg)
            xchg.load_markets()

    return exchanges
