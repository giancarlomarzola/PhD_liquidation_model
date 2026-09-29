from __future__ import annotations
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from environment.defi_env import DefiEnv, Wallet, Token, LendingPool
from environment.parameters import pool_parameters


# ========================================================================================================================
# Actions: the output of a strategy
# ========================================================================================================================


class ActionType(Enum):
    SUPPLY = "supply"
    WITHDRAW = "withdraw"
    BORROW = "borrow"
    REPAY = "repay"
    TRANSFER = "transfer"  # withdraw from `pool`, swap at oracle price, supply to `target_pool`


@dataclass(frozen=True)
class Action:
    """
    A single transaction a strategy wants the agent to carry out.
    `amount` is denominated in units of `pool`'s underlying token.
    """

    kind: ActionType
    pool: LendingPool
    amount: float
    target_pool: LendingPool | None = None

    def __repr__(self) -> str:
        target = f" -> {self.target_pool.underlying_token.symbol}" if self.target_pool else ""
        return (
            f"Action({self.kind.value} {self.amount:,.6f} "
            f"{self.pool.underlying_token.symbol}{target})"
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "pool": self.pool.underlying_token.symbol,
            "amount": self.amount,
            "target_pool": self.target_pool.underlying_token.symbol if self.target_pool else None,
        }


@dataclass(frozen=True)
class Transaction:
    """An attempted Action and its outcome, as logged by the Agent."""

    block: int
    action: Action
    error: str | None = None
    received: float | None = None  # TRANSFER only: amount of `target_pool`'s token supplied

    @property
    def success(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "block": self.block,
            **self.action.to_dict(),
            "received": self.received,
            "success": self.success,
            "error": self.error,
        }


# ========================================================================================================================
# Triggers: conditions on the environment / wallet that decide *when* a rule fires
# ========================================================================================================================


class Trigger(ABC):
    """
    Condition evaluated once per agent step.
    Stateful triggers keep their state per agent (keyed by agent name), so a single
    strategy instance can be shared between many agents.
    """

    @abstractmethod
    def is_triggered(self, agent: Agent) -> bool: ...


class PriceChangeTrigger(Trigger):
    """
    Fires when the price of `symbol` has moved by `threshold` relative to a reference price.
    threshold > 0: fires on a rise of at least threshold (e.g. 0.10 = +10%)
    threshold < 0: fires on a drop of at least |threshold| (e.g. -0.10 = -10%)
    The reference price is the price when the agent first saw it, reset every time the trigger fires.
    """

    def __init__(self, symbol: str, threshold: float):
        assert threshold != 0, "Threshold must be non-zero"
        self.symbol = symbol
        self.threshold = threshold
        self._reference_price: dict[str, float] = {}

    def is_triggered(self, agent: Agent) -> bool:
        price = agent.env.prices[self.symbol]
        reference = self._reference_price.setdefault(agent.name, price)
        change = (price - reference) / reference
        fired = change >= self.threshold if self.threshold > 0 else change <= self.threshold
        if fired:
            self._reference_price[agent.name] = price
        return fired


class HealthFactorTrigger(Trigger):
    """Fires while the agent's health factor is below `below`."""

    def __init__(self, below: float):
        self.below = below

    def is_triggered(self, agent: Agent) -> bool:
        return agent.wallet.health_factor < self.below


class BlockIntervalTrigger(Trigger):
    """Fires every `every` blocks, counted from the first block the agent is evaluated."""

    def __init__(self, every: int):
        assert every > 0, "Interval must be positive"
        self.every = every
        self._last_fired: dict[str, int] = {}

    def is_triggered(self, agent: Agent) -> bool:
        block = agent.env.blocknumber
        last = self._last_fired.setdefault(agent.name, block)
        if block - last >= self.every:
            self._last_fired[agent.name] = block
            return True
        return False


class ProbabilityTrigger(Trigger):
    """Fires with probability `p` each time it is evaluated."""

    def __init__(self, p: float, seed: int | None = None):
        assert 0 <= p <= 1, "Probability must be in [0, 1]"
        self.p = p
        self.rng = random.Random(seed)

    def is_triggered(self, agent: Agent) -> bool:
        return self.rng.random() < self.p


# ========================================================================================================================
# Strategies
# ========================================================================================================================


class Strategy(ABC):
    """
    Base class for agent strategies.

    A strategy inspects the agent and environment and returns the ordered list of
    Actions the agent should carry out this step. It never executes anything itself.

    Amounts are sized as a `fraction` of the maximum feasible amount for that action
    (see `max_amount`), so strategies don't produce transactions the pools would reject.

    Parameters
    ----------
    min_health_factor : float
        Withdrawals, transfers and borrows are capped so the agent's health factor stays
        at or above this value.
    """

    def __init__(self, min_health_factor: float = 1.05):
        assert min_health_factor > 1, "min_health_factor must be > 1 (pools reject HF <= 1)"
        self.min_health_factor = min_health_factor

    @abstractmethod
    def decide(self, agent: Agent) -> list[Action]: ...

    # --- Sizing helpers -------------------------------------------------------------------------------------------

    def max_amount(
        self,
        agent: Agent,
        kind: ActionType,
        pool: LendingPool,
        target_pool: LendingPool | None = None,
    ) -> float:
        """Largest amount (in `pool` underlying units) of `kind` the agent can currently transact."""
        wallet = agent.wallet

        if kind is ActionType.SUPPLY:
            return min(wallet.balances.get(pool.underlying_token, 0.0), pool.supply_room)

        if kind is ActionType.REPAY:
            return min(
                pool.get_actual_borrow_balance(wallet),
                wallet.balances.get(pool.underlying_token, 0.0),
            )

        if kind is ActionType.BORROW:
            headroom_usd = (
                wallet.weighted_collateral_usd / self.min_health_factor
                - wallet.total_borrowed_usd
            )
            amount = headroom_usd / pool.underlying_token.price
            return max(0.0, min(amount, pool.available_liquidity_cash, pool.borrow_room))

        if kind in (ActionType.WITHDRAW, ActionType.TRANSFER):
            amount = min(
                pool.get_actual_supply_balance(wallet),
                pool.available_liquidity_cash,
                self._max_safe_withdraw(wallet, pool),
            )
            if kind is ActionType.TRANSFER:
                assert target_pool is not None and target_pool is not pool, "Transfer needs a different target_pool"
                price_ratio = target_pool.underlying_token.price / pool.underlying_token.price
                amount = min(amount, target_pool.supply_room * price_ratio)
            # Tiny haircut: withdrawing the exact full balance can fail the aToken burn on float rounding
            return max(0.0, amount * (1 - 1e-12))

        raise ValueError(f"Unknown action type {kind}")

    def sized_action(
        self,
        agent: Agent,
        kind: ActionType,
        pool: LendingPool,
        fraction: float,
        target_pool: LendingPool | None = None,
    ) -> Action | None:
        """Action for `fraction` of the max feasible amount, or None if nothing can be transacted."""
        assert 0 < fraction <= 1, "Fraction must be in (0, 1]"
        amount = fraction * self.max_amount(agent, kind, pool, target_pool)
        if amount <= 0:
            return None
        return Action(kind, pool, amount, target_pool)

    def _max_safe_withdraw(self, wallet: Wallet, pool: LendingPool) -> float:
        # HF = weighted_collateral / debt  ->  solve for withdrawal x keeping HF >= min_health_factor
        debt_usd = wallet.total_borrowed_usd
        if debt_usd == 0:
            return pool.get_actual_supply_balance(wallet)
        excess_usd = wallet.weighted_collateral_usd - self.min_health_factor * debt_usd
        return max(0.0, excess_usd / (pool.underlying_token.price * pool.liquidation_threshold))


@dataclass
class Rule:
    """
    When `trigger` fires, transact `fraction` of the max feasible amount of `action`
    in the pool of `pool` (underlying token symbol). `target_pool` is only used for TRANSFER.
    """

    trigger: Trigger
    action: ActionType
    pool: str
    fraction: float
    target_pool: str | None = None

    def __post_init__(self):
        assert 0 < self.fraction <= 1, "Fraction must be in (0, 1]"
        if self.action is ActionType.TRANSFER:
            assert self.target_pool is not None, "TRANSFER rules need a target_pool"
            assert self.target_pool != self.pool, "target_pool must differ from pool"
        else:
            assert self.target_pool is None, "target_pool is only used by TRANSFER rules"


class RuleBasedStrategy(Strategy):
    """
    Strategy defined by a list of trigger -> action rules, evaluated in order each step.
    All rules are sized against the state at the start of the step.

    Example (contrarian: withdraw into price rises, deposit into price drops):
        RuleBasedStrategy([
            Rule(PriceChangeTrigger("wbtc", +0.02), ActionType.WITHDRAW, "wbtc", fraction=0.1),
            Rule(PriceChangeTrigger("wbtc", -0.02), ActionType.SUPPLY, "wbtc", fraction=0.1),
        ])
    """

    def __init__(self, rules: list[Rule], min_health_factor: float = 1.05):
        super().__init__(min_health_factor)
        self.rules = rules

    def decide(self, agent: Agent) -> list[Action]:
        pools = agent.env.lending_pools
        actions = []
        for rule in self.rules:
            if not rule.trigger.is_triggered(agent):
                continue
            target_pool = pools[rule.target_pool] if rule.target_pool else None
            action = self.sized_action(agent, rule.action, pools[rule.pool], rule.fraction, target_pool)
            if action:
                actions.append(action)
        return actions


class RandomStrategy(Strategy):
    """
    Carries out random transactions: supplying more tokens, withdrawing supplied tokens,
    or transferring supplied value from one lending pool to another.

    Each step the agent acts with probability `activity_probability`. If it acts, an action
    type is drawn according to `weights` (restricted to types that are currently feasible),
    then a random feasible pool (pair), and a random fraction in [min_fraction, max_fraction]
    of the max feasible amount.
    """

    DEFAULT_WEIGHTS = {
        ActionType.SUPPLY: 1.0,
        ActionType.WITHDRAW: 1.0,
        ActionType.TRANSFER: 1.0,
    }

    def __init__(
        self,
        activity_probability: float = 0.1,
        weights: dict[ActionType, float] | None = None,
        min_fraction: float = 0.05,
        max_fraction: float = 0.5,
        seed: int | None = None,
        min_health_factor: float = 1.05,
    ):
        super().__init__(min_health_factor)
        assert 0 <= activity_probability <= 1, "activity_probability must be in [0, 1]"
        assert 0 < min_fraction <= max_fraction <= 1, "Need 0 < min_fraction <= max_fraction <= 1"
        self.activity_probability = activity_probability
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)
        self.min_fraction = min_fraction
        self.max_fraction = max_fraction
        self.rng = random.Random(seed)

    def decide(self, agent: Agent) -> list[Action]:
        if self.rng.random() >= self.activity_probability:
            return []

        options = {
            kind: self._feasible_options(agent, kind)
            for kind, weight in self.weights.items()
            if weight > 0
        }
        options = {kind: opts for kind, opts in options.items() if opts}
        if not options:
            return []

        kinds = list(options)
        kind = self.rng.choices(kinds, weights=[self.weights[k] for k in kinds])[0]
        pool, target_pool = self.rng.choice(options[kind])
        fraction = self.rng.uniform(self.min_fraction, self.max_fraction)
        action = self.sized_action(agent, kind, pool, fraction, target_pool)
        return [action] if action else []

    def _feasible_options(
        self, agent: Agent, kind: ActionType
    ) -> list[tuple[LendingPool, LendingPool | None]]:
        pools = list(agent.env.lending_pools.values())
        if kind is ActionType.TRANSFER:
            candidates = [(src, dst) for src in pools for dst in pools if src is not dst]
        else:
            candidates = [(pool, None) for pool in pools]
        return [
            (pool, target_pool)
            for pool, target_pool in candidates
            if self.max_amount(agent, kind, pool, target_pool) > 0
        ]

# ========================================================================================================================
# Liquidator Strategy
# ========================================================================================================================
# TODO: Actually write this
class LiquidatorStrategy ():
    pass


# ========================================================================================================================
# Agent
# ========================================================================================================================


class Agent:
    """
    Market participant with a wallet. Each step, `enact_strategy` asks the agent's Strategy
    for Actions and executes them, logging every attempt in `transactions`.
    An agent without a strategy only acts on manually passed `extra_actions`.
    """

    def __init__(
        self,
        name: str,
        env: DefiEnv,
        wallet: Wallet | None = None,
        strategy: Strategy | None = None,
        liquidator_strategy: LiquidatorStrategy | None = None,
        initial_endowment: dict[Token, float] | None = None,
    ):
        self.env = env
        self.name = name
        self.history = []
        self.transactions: list[Transaction] = []  # every attempted Action, with outcome
        self.strategy = strategy  # None = agent never acts on its own
        self.liquidator_strategy = liquidator_strategy

        self.wallet = wallet or Wallet(env, name, None)

        if initial_endowment:
            for token, amount in initial_endowment.items():
                token.mint(self.wallet, amount)

    def enact_strategy(self, extra_actions: list[Action] | None = None) -> list[Action]:
        """
        Ask the strategy which transactions to carry out, then execute them (plus any
        manually specified `extra_actions`). Rejected transactions are logged, not raised.
        """
        actions = self.strategy.decide(self) if self.strategy else []
        actions += extra_actions or []
        for action in actions:
            #TODO: Should i shuffle the order of actions in here?
            error, received = None, None
            try:
                received = self.execute(action)
            except AssertionError as e:
                error = str(e)
            self.transactions.append(Transaction(self.env.blocknumber, action, error, received))
        return actions

    def execute(self, action: Action) -> float | None:
        """Carry out `action`. For TRANSFER, returns the amount supplied to `target_pool`."""
        if action.kind is not ActionType.TRANSFER:
            # ActionType values match the Wallet method names (supply, withdraw, borrow, repay)
            getattr(self.wallet, action.kind.value)(action.pool, action.amount)
            return None
        self.wallet.withdraw(action.pool, action.amount)
        received = self._swap(
            action.pool.underlying_token, action.target_pool.underlying_token, action.amount
        )
        self.wallet.supply(action.target_pool, received)
        return received

    def _swap(self, sell: Token, buy: Token, amount: float) -> float:
        """Idealised swap at oracle prices (no DEX, no slippage or fees)."""
        received = amount * sell.price / buy.price
        sell.burn(self.wallet, amount)
        buy.mint(self.wallet, received)
        return received

    def record_state(self) -> dict:
        # Record current state for analysis.
        state = {
            'block': self.env.blocknumber,
            'health_factor': self.wallet.health_factor,
            'total_supplied_usd': self.wallet.total_supplied_usd,
            'total_borrowed_usd': self.wallet.total_borrowed_usd,
            'available_collateral_usd': self.wallet.available_collateral_usd,
        }
        self.history.append(state)
        return state


if __name__ == "__main__":
    # 1: set up market env with tokens and pools
    defi_env = DefiEnv(prices={"usdc": 1.00, "wbtc": 50_000.00})

    usdc = Token(defi_env, "usdc")
    wbtc = Token(defi_env, "wbtc")

    usdc_pool = LendingPool(env=defi_env, underlying_token=usdc, **pool_parameters["usdc"])
    wbtc_pool = LendingPool(env=defi_env, underlying_token=wbtc, **pool_parameters["wbtc"])

    # 2: define strategies
    # Contrarian: withdraws wbtc into price rises, supplies into price drops
    contrarian = RuleBasedStrategy(
        [
            Rule(PriceChangeTrigger("wbtc", +0.02), ActionType.WITHDRAW, "wbtc", fraction=0.1),
            Rule(PriceChangeTrigger("wbtc", -0.02), ActionType.SUPPLY, "wbtc", fraction=0.1),
        ]
    )

    # Panic withdrawer: supplies periodically, pulls out when the market crashes
    panic_withdrawer = RuleBasedStrategy(
        [
            Rule(BlockIntervalTrigger(every=50), ActionType.SUPPLY, "wbtc", fraction=0.2),
            Rule(PriceChangeTrigger("wbtc", -0.10), ActionType.WITHDRAW, "wbtc", fraction=0.5),
        ]
    )

    # Leveraged borrower: supplies wbtc, borrows usdc, repays when the health factor gets low
    leveraged_borrower = RuleBasedStrategy(
        [
            Rule(BlockIntervalTrigger(every=10), ActionType.SUPPLY, "wbtc", fraction=1.0),
            Rule(BlockIntervalTrigger(every=10), ActionType.BORROW, "usdc", fraction=0.5),
            Rule(HealthFactorTrigger(below=1.3), ActionType.REPAY, "usdc", fraction=1.0),
        ],
        min_health_factor=1.2,
    )

    # Rotator: keeps wbtc supplied, moves half of it into the usdc pool on every 5% drop
    rotator = RuleBasedStrategy(
        [
            Rule(BlockIntervalTrigger(every=1), ActionType.SUPPLY, "wbtc", fraction=1.0),
            Rule(
                PriceChangeTrigger("wbtc", -0.05),
                ActionType.TRANSFER,
                "wbtc",
                fraction=0.5,
                target_pool="usdc",
            ),
        ]
    )

    # 3: create agents. Strategies can be shared: stateful triggers keep state per agent name
    # Passive liquidity provider with no strategy, supplies once so there is usdc to borrow
    whale = Agent("whale", defi_env, initial_endowment={usdc: 5_000_000, wbtc: 100})
    whale.enact_strategy(
        extra_actions=[
            Action(ActionType.SUPPLY, usdc_pool, 5_000_000),
            Action(ActionType.SUPPLY, wbtc_pool, 100),
        ]
    )

    agents = [whale]
    agents += [
        Agent(f"contrarian_{i}", defi_env, strategy=contrarian, initial_endowment={wbtc: 1, usdc: 20_000})
        for i in range(3)
    ]
    agents += [
        Agent(f"panic_{i}", defi_env, strategy=panic_withdrawer, initial_endowment={wbtc: 2})
        for i in range(3)
    ]
    agents += [
        Agent(f"borrower_{i}", defi_env, strategy=leveraged_borrower, initial_endowment={wbtc: 1})
        for i in range(2)
    ]
    agents += [Agent("rotator", defi_env, strategy=rotator, initial_endowment={wbtc: 1})]
    agents += [
        Agent(
            f"random_{i}",
            defi_env,
            strategy=RandomStrategy(activity_probability=0.2, seed=i),
            initial_endowment={wbtc: 0.5, usdc: 10_000},
        )
        for i in range(3)
    ]

    # 4: run a short simulation: noisy wbtc price for 150 blocks, then a ~25% crash
    rng = random.Random(42)
    price = defi_env.prices["wbtc"]
    for step in range(200):
        drift = -0.006 if step >= 150 else 0.0
        price *= 1 + drift + rng.gauss(0, 0.005)
        defi_env.advance_blocks(1, new_prices={"usdc": 1.00, "wbtc": price})
        for agent in agents:
            agent.enact_strategy()
            agent.record_state()

    # 5: summary
    print(f"Final wbtc price: {price:,.2f}\n")
    print(f"{'agent':<14}{'txs':>5}{'failed':>8}{'supplied $':>16}{'borrowed $':>14}{'HF':>8}")
    for agent in agents:
        # TODO: For actual simulation, shuffle agent list order for each step
        failed = sum(not tx.success for tx in agent.transactions)
        state = agent.history[-1]
        print(
            f"{agent.name:<14}{len(agent.transactions):>5}{failed:>8}"
            f"{state['total_supplied_usd']:>16,.2f}{state['total_borrowed_usd']:>14,.2f}"
            f"{state['health_factor']:>8.3f}"
        )

    for name in ("rotator", "borrower_0"):
        print(f"\nLast transactions of {name}:")
        agent = next(a for a in agents if a.name == name)
        for tx in agent.transactions[-4:]:
            print("  ", tx.to_dict())
