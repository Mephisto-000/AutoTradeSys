# AutoTradeSys fork addition (2026-10-25): an offline stand-in for the shioaji SDK.
"""A stand-in for the shioaji SDK (the 1.7 surface lib/sinopac_session reads)
for the SinoPac tests — no network, no keys.

    import sinopac_fake
    broker = sinopac_fake.install()      # puts a fake `shioaji` in sys.modules

`broker` is the fake exchange the tests drive: quotes, cash, settlements,
cash-share positions, and how orders fill (board / odd / fail / cancel knobs).
Enums behave like 1.7's native ones: str() is 'OrderStatus.Filled', `.value`
is 'Filled' — the trap lib/sinopac_session.enum_value exists for.
"""
import itertools
import sys
import types


class _Enum:
    def __init__(self, cls, name, value=None):
        self._cls, self.name = cls, name
        self.value = name if value is None else value

    def __str__(self):
        return f"{self._cls}.{self.name}"

    def __repr__(self):
        return f"<{self._cls}.{self.name}: {self.value!r}>"

    def __eq__(self, other):
        if isinstance(other, _Enum):
            return other._cls == self._cls and other.value == self.value
        return other == self.value

    def __hash__(self):
        return hash((self._cls, self.value))


def _enum(cls, names, values=None):
    return types.SimpleNamespace(**{n: _Enum(cls, n, (values or {}).get(n)) for n in names})


Action = _enum("Action", ["Buy", "Sell"])
StockPriceType = _enum("StockPriceType", ["LMT", "MKT"])
OrderType = _enum("OrderType", ["ROD", "IOC", "FOK"])
StockOrderLot = _enum("StockOrderLot", ["Common", "Odd", "IntradayOdd", "Fixing", "BlockTrade"])
StockOrderCond = _enum("StockOrderCond", ["Cash", "MarginTrading", "ShortSelling"])
Unit = _enum("Unit", ["Common", "Share"])
OrderStatus = _enum("OrderStatus", ["Cancelled", "Failed", "Filled", "Inactive", "PartFilled",
                                    "PendingSubmit", "PreSubmitted", "Submitted"])
SecurityType = _enum("SecurityType", ["Stock", "Futures", "Index"],
                     {"Stock": "STK", "Futures": "FUT", "Index": "IND"})
AccountType = _enum("AccountType", ["Stock", "Future"], {"Stock": "S", "Future": "F"})


class ShioajiError(Exception):
    pass


class AuthError(ShioajiError):
    pass


class TokenError(AuthError):
    pass


class ShioajiConnectionError(ShioajiError, ConnectionError):
    pass


class ShioajiTimeoutError(ShioajiError, TimeoutError):
    pass


class ResponseError(ShioajiError):
    pass


class OrderOutcomeUnknownError(ResponseError):
    pass


class CaError(ShioajiError):
    pass


class StockOrder:
    def __init__(self, action, price, quantity, price_type, time_in_force=None, order_lot=None,
                 order_cond=None, daytrade_short=None, custom_field=None, account=None, *,
                 order_type=None):
        self.action, self.price, self.quantity, self.price_type = action, price, quantity, price_type
        self.order_type = order_type or time_in_force
        self.order_lot, self.order_cond = order_lot, order_cond
        self.custom_field, self.account = custom_field, account


class Account:
    def __init__(self):
        self.account_type = AccountType.Stock
        self.person_id, self.broker_id, self.account_id = "A123456789", "9A95", "1234567"
        self.signed, self.username = True, "tester"


class Broker:
    """The fake exchange + its knobs."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.quotes = {}       # code -> dict(close, bid, ask, reference, limit_up, limit_down, ...)
        self.positions = {}    # code -> cash shares held
        self.cash = 1_000_000.0
        self.settlements = []  # [(date 'YYYY-MM-DD', T, amount)]
        self.board_fill = "full"     # full | partial | none   (IOC board lots)
        self.odd_fill = "full"       # full | partial | never  (ROD odd lots / auction board lots)
        self.fail_msg = None         # a str → every new order Failed with this msg
        self.cancel_confirms = True
        self.place_raises = None     # an exception instance place_order raises once
        self.place_raises_after = False  # True: the order still lands on the book
        self.balance_raises = None
        self.cash_moves = True       # False: a fill leaves the bank balance alone (T+2, as live)
        self.kbars_source = None     # (code, start, end) -> dict of lists
        self.unknown = set()         # codes contracts.get() does not know
        self.info_extra = {}         # code -> extra StockInfo fields
        self.logins = self.logouts = 0
        self.login_kwargs = []
        self.ca_calls = []
        self.trades = []
        self.placed = []             # (contract code, StockOrder)
        self.cancels = []
        self.kbars_calls = []
        self.snapshot_calls = 0
        self.login_raises = None
        self.seq = itertools.count(1)

    def quote(self, code, close, bid=None, ask=None, reference=None, limit_up=None, limit_down=None):
        ref = reference if reference is not None else close
        self.quotes[code] = dict(close=close, bid=close if bid is None else bid,
                                 ask=close if ask is None else ask, reference=ref,
                                 limit_up=round(ref * 1.1, 2) if limit_up is None else limit_up,
                                 limit_down=round(ref * 0.9, 2) if limit_down is None else limit_down)


BROKER = Broker()


class _Contract:
    def __init__(self, code):
        self.code = code
        self.security_type = SecurityType.Stock
        self.exchange = "TSE"
        self.target_code = None


class _Info:
    def __init__(self, code):
        q = BROKER.quotes.get(code, {})
        self.code = code
        self.reference = q.get("reference", 0.0)
        self.limit_up = q.get("limit_up", 0.0)
        self.limit_down = q.get("limit_down", 0.0)
        self.trading_suspended = False
        self.disposition_prepay_ratio = None
        for k, v in BROKER.info_extra.get(code, {}).items():
            setattr(self, k, v)


class _ContractsApi:
    def get(self, code, region=None, security_type=None, exchange=None):
        return None if code in BROKER.unknown else _Contract(code)

    def info(self, base):
        return _Info(base.code)


class _Deal:
    def __init__(self, price, quantity):
        self.seq = f"{next(BROKER.seq):06d}"
        self.price, self.quantity, self.ts = price, quantity, 0.0


class _Status:
    def __init__(self, qty):
        self.status = OrderStatus.PendingSubmit
        self.deals = []
        self.order_quantity = qty
        self.deal_quantity = 0
        self.cancel_quantity = 0
        self.msg = ""


class _OrderResult:
    def __init__(self, order):
        n = next(BROKER.seq)
        self.id = f"id{n}"
        self.seqno = f"{n:06d}"
        self.ordno = f"X{n:04d}"
        self.quantity = order.quantity
        self.price = order.price
        self.custom_field = order.custom_field
        self.action = order.action
        self.order_lot = order.order_lot
        self.order_type = order.order_type
        self.price_type = order.price_type


class Trade:
    def __init__(self, contract, order):
        self.contract = contract
        self.order = _OrderResult(order)
        self.status = _Status(order.quantity)
        self._polls = 0
        self._cancel_requested = False


def _fill_price(trade):
    q = BROKER.quotes[trade.contract.code]
    limit = float(trade.order.price or 0)
    if trade.order.action == "Buy":
        return min(limit, q["ask"]) if limit else q["ask"]
    return max(limit, q["bid"]) if limit else q["bid"]


def _book(trade, qty):
    """A fill moves the fake account: positions in shares, cash at once."""
    mult = 1000 if trade.order.order_lot == "Common" else 1
    px = _fill_price(trade)
    trade.status.deals.append(_Deal(px, qty))
    trade.status.deal_quantity += qty
    code = trade.contract.code
    shares = qty * mult
    if trade.order.action == "Buy":
        BROKER.positions[code] = BROKER.positions.get(code, 0) + shares
        BROKER.cash -= shares * px if BROKER.cash_moves else 0
    else:
        BROKER.positions[code] = BROKER.positions.get(code, 0) - shares
        BROKER.cash += shares * px if BROKER.cash_moves else 0


def _advance(trade):
    st = trade.status
    if st.status in ("Filled", "Cancelled", "Failed"):
        return
    trade._polls += 1
    qty = trade.order.quantity
    if BROKER.fail_msg:
        st.status, st.msg = OrderStatus.Failed, BROKER.fail_msg
        return
    if trade._polls == 1:
        st.status = OrderStatus.Submitted
    ioc = trade.order.order_type == "IOC"
    if ioc:
        if BROKER.board_fill == "full":
            _book(trade, qty)
            st.status = OrderStatus.Filled
        elif BROKER.board_fill == "partial":
            _book(trade, max(1, qty // 2))
            st.cancel_quantity = qty - st.deal_quantity
            st.status = OrderStatus.Cancelled
        else:
            st.cancel_quantity = qty
            st.status = OrderStatus.Cancelled
        return
    if trade._cancel_requested and BROKER.cancel_confirms:
        st.cancel_quantity = qty - st.deal_quantity
        st.status = OrderStatus.Cancelled
        return
    if trade._polls >= 2 and BROKER.odd_fill == "full" and st.deal_quantity < qty:
        _book(trade, qty - st.deal_quantity)
        st.status = OrderStatus.Filled
    elif trade._polls == 2 and BROKER.odd_fill == "partial":
        _book(trade, max(1, qty // 2))
        st.status = OrderStatus.PartFilled


class _Snapshot:
    def __init__(self, code):
        q = BROKER.quotes[code]
        self.code, self.close = code, q["close"]
        self.buy_price, self.sell_price = q["bid"], q["ask"]


class _Position:
    def __init__(self, code, qty, cond="Cash"):
        q = BROKER.quotes.get(code, {"close": 0.0})
        self.code, self.quantity = code, qty
        self.direction = Action.Buy
        self.cond = getattr(StockOrderCond, cond)
        self.price, self.last_price, self.pnl = q["close"] * 0.9, q["close"], 0.0


class _Balance:
    def __init__(self, cash):
        self.acc_balance, self.errmsg, self.status, self.date = cash, "", "Fetched", ""


class _Settlement:
    def __init__(self, date, t, amount):
        self.date, self.T, self.amount = date, t, amount


class _Usage:
    bytes, limit_bytes, connections, remaining_bytes = 1_000_000, 500_000_000, 1, 499_000_000


class _KBars:
    def __init__(self, d):
        for k in ("ts", "Open", "High", "Low", "Close", "Volume", "Amount"):
            setattr(self, k, list(d.get(k, [])))


class Shioaji:
    def __init__(self, simulation=False, **_):
        self.simulation = simulation
        self.contracts = _ContractsApi()
        self._account = Account()
        self._trades = BROKER.trades

    def login(self, api_key, secret_key, subscribe_trade=True, receive_window=30000,
              force_refresh=False):
        BROKER.logins += 1
        BROKER.login_kwargs.append({"subscribe_trade": subscribe_trade})
        if BROKER.login_raises:
            raise BROKER.login_raises
        return [self._account]

    def logout(self):
        BROKER.logouts += 1
        return True

    def activate_ca(self, ca_path, ca_passwd, person_id=None):
        BROKER.ca_calls.append((ca_path, person_id))
        return True

    @property
    def stock_account(self):
        return self._account

    def list_accounts(self):
        return [self._account]

    def usage(self, timeout=30000, cb=None):
        return _Usage()

    def snapshots(self, contracts, timeout=30000, cb=None):
        BROKER.snapshot_calls += 1
        return [_Snapshot(c.code) for c in contracts]

    def kbars(self, contract, start=None, end=None, timeout=30000, cb=None):
        BROKER.kbars_calls.append((contract.code, start, end))
        return _KBars(BROKER.kbars_source(contract.code, start, end) if BROKER.kbars_source else {})

    def place_order(self, contract, order, timeout=30000, cb=None):
        BROKER.placed.append((contract.code, order))
        if BROKER.place_raises is not None:
            exc, BROKER.place_raises = BROKER.place_raises, None
            if BROKER.place_raises_after:
                BROKER.trades.append(Trade(contract, order))
            raise exc
        t = Trade(contract, order)
        BROKER.trades.append(t)
        return t

    def cancel_order(self, trade, timeout=30000, cb=None):
        BROKER.cancels.append(trade.order.seqno)
        trade._cancel_requested = True
        return trade

    def update_status(self, account=None, *, trade=None, timeout=30000, cb=None):
        for t in ([trade] if trade is not None else BROKER.trades):
            _advance(t)

    def list_trades(self):
        return list(BROKER.trades)

    def list_positions(self, account=None, unit=None, timeout=30000, cb=None):
        return [_Position(c, q) for c, q in BROKER.positions.items() if q > 0]

    def account_balance(self, account=None, timeout=30000, cb=None):
        if BROKER.balance_raises is not None:
            raise BROKER.balance_raises
        if self.simulation:
            raise ShioajiError("not available in simulation")
        return _Balance(BROKER.cash)

    def settlements(self, account=None, timeout=30000, cb=None):
        return [_Settlement(d, t, a) for d, t, a in BROKER.settlements]

    def get_ca_expiretime(self, person_id):
        return "2027-01-01"


def install():
    """Put the fake SDK in sys.modules (before lib/sinopac_session imports it) and
    hand back the fake exchange."""
    mod = types.ModuleType("shioaji")
    mod.__version__ = "1.7.9-fake"
    for name, obj in dict(
            Action=Action, StockPriceType=StockPriceType, OrderType=OrderType,
            StockOrderLot=StockOrderLot, StockOrderCond=StockOrderCond, Unit=Unit,
            OrderStatus=OrderStatus, SecurityType=SecurityType, AccountType=AccountType,
            StockOrder=StockOrder, Shioaji=Shioaji, ShioajiError=ShioajiError, AuthError=AuthError,
            TokenError=TokenError, ShioajiConnectionError=ShioajiConnectionError,
            ShioajiTimeoutError=ShioajiTimeoutError, ResponseError=ResponseError,
            OrderOutcomeUnknownError=OrderOutcomeUnknownError, CaError=CaError).items():
        setattr(mod, name, obj)
    sys.modules["shioaji"] = mod
    BROKER.reset()
    return BROKER
