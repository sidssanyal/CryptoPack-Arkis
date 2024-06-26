import logging
import time
import os
import os.path as path
import platform

local_dir =  path.abspath(path.join(__file__ ,"../"))
folder_name = local_dir + "/_log"

try:
    os.mkdir(folder_name)
except FileExistsError:
    _log_ = 1
except Exception as e:
    print(f"Failed to create folder '{folder_name}': {e}")

from datetime import datetime
current_time = datetime.now()

with open(folder_name + "/running.log", "a") as fr:
    fr.write(current_time.strftime("%Y-%m-%d %H:%M:%S") + "\n")

from order_book_recorder.depth import Side, calculate_price_at_depths
from order_book_recorder.utils import to_async

from asyncio import Task, create_task
from typing import Optional, Dict, List, Union, Callable
from concurrent.futures import ThreadPoolExecutor
#from ccxtpro.base.exchange import Exchange as ProExchange
#from ccxt.base.exchange import Exchange as SyncExchange
#from ccxt.base.errors import RateLimitExceeded, ExchangeNotAvailable, RequestTimeout

# Create a thread pool where sync exchange APIs will be executed
sync_exchange_thread_pool = ThreadPoolExecutor()


logger = logging.getLogger(__name__)


class Watcher:

    exchange_name: str
    market: str
    exchange: Union[ProExchange, SyncExchange]
    orderbook: dict
    task: Optional[Task]
    done: bool

    def __init__(self, exchange_name: str, pair: str, exchange, depth_levels: List[float]):
        """

        :param exchange_name: Human readable name for this exchange
        :param pair: e.g. BTC/EUR
        :param exchange: CCXT/CCXT Pro exchange object
        :param depth_levels: Watched depth levels
        """
        self.exchange_name = exchange_name
        self.market = pair
        self.exchange = exchange
        self.task = None
        self.done = False
        self.depth_levels = depth_levels
        self.task_count = 0

        self.ask_price = None
        self.bid_price = None

        # [quantity target, price] maps
        self.ask_levels = {}
        self.bid_levels = {}

        # Hacky hack
        watch_order_book_limits = {
            "Bitfinex": 100,
            "Kraken": 500,
        }

        watch_limit = watch_order_book_limits.get(self.exchange_name, 200)

        self.order_book_limit = watch_limit

        # Sync API throttling
        self.min_fetch_delay = 2.0
        self.last_fetch = 0

    async def start_watching(self) -> "WatchedExchange":
        """Options

        - Sync API
        - ASync API
        """

        if hasattr(self.exchange, "watch_order_book"):
            # CCXT PRO
            self.orderbook = await self.watch_async()
        else:
            # CCXT
            # Sync (Exmo) or async API (Gemini)
            self.orderbook = await self.watch_sync()
        self.done = True
        return self

    async def watch_async(self):
        return await self.exchange.watch_order_book(self.market, limit=self.order_book_limit)

    @to_async(executor=sync_exchange_thread_pool)
    def watch_sync(self):
        """Wrap a sync API in a thread pool execution."""
        tries = 10
        delay = 1.0

        needs_sleeping = self.min_fetch_delay - (time.time() - self.last_fetch)
        if needs_sleeping > 0:
            # logger.info("Adding some sleep for %s: %f", self.exchange_name, needs_sleeping)
            time.sleep(needs_sleeping)

        while tries:
            try:
                order_book = self.exchange.fetch_order_book(self.market, limit=self.order_book_limit)
                self.last_fetch = time.time()
                return order_book
            except RateLimitExceeded:
                logger.warning("Rate limit exceeded on %s, tries %d, delay %s", self.exchange_name, tries, delay)
                time.sleep(delay)
                tries -= 1
                delay *= 1.25
            except RequestTimeout:
                # Gemini again
                logger.warning("Exchange timed out %s", self.exchange_name)
                return {"asks": [], "bids": []}
            except ExchangeNotAvailable:
                # <head><title>502 Bad Gateway</title></head>
                # ccxt.base.errors.ExchangeNotAvailable: gemini GET https://api.gemini.com/v1/book/btcgbp?limit_bids=100&limit_asks=100 502 Bad Gateway <html>
                logger.warning("Exchange not available %s", self.exchange_name)
                return {"asks": [], "bids": []}

    def create_task(self):
        self.done = False
        self.task_count += 1
        self.task = create_task(self.start_watching(), name=f"{self.exchange_name}: {self.market} task #{self.task_count}")
        return self.task

    def is_task_pending(self):
        if self.task is None:
            return False

        if self.done:
            return False

        return True

    def is_done(self):
        if self.task is None:
            return False

        if self.done:
            return True

        return False

    def has_data(self):
        return self.ask_price is not None

    def refresh_depths(self):
        """Update exchange market depths"""
        #  BTC/GBP [42038.45, 0.083876] [42017.45, 0.03815124]

        if len(self.orderbook["asks"]) > 0:
            # Gemini can return empty orderbook when it crashes
            self.ask_price = self.orderbook["asks"][0][0]

        if len(self.orderbook["bids"]) > 0:
            self.bid_price = self.orderbook["bids"][0][0]

        ask_success, self.ask_levels, max_ask = calculate_price_at_depths(self.orderbook["asks"], Side.ask, self.depth_levels)
        bid_success, self.bid_levels, max_bid = calculate_price_at_depths(self.orderbook["bids"], Side.bid, self.depth_levels)

        if not ask_success:
            logger.warning("Could not map out ask levels %s on %s %s, got max ask inventory %f", self.exchange_name, self.market, self.depth_levels, max_ask)

        if not bid_success:
            logger.warning("Could not map out bid levels %s on %s %s, got max bid inventory %f", self.exchange_name, self.market, self.depth_levels, max_bid)

    def get_spread(self):
        assert self.has_data()
        return (self.ask_price - self.bid_price) / self.bid_price

    def get_depth_record(self) -> Dict:
        """Export the current orderbook levels for Redis"""
        return {
            "exchange_name": self.exchange_name,
            "market": self.market,
            "ask_levels": self.ask_levels,
            "bid_levels": self.bid_levels,
        }
