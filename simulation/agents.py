"""Agent behaviors and strategies for simulations."""

from dataclasses import dataclass
from typing import Optional, Callable
from environment.defi_env import Wallet, DefiEnv, LendingPool


@dataclass
class LiquidatorStrategy:
    """Configuration for liquidator behavior."""

    enabled: bool = True
    target_health_factor: float = 0.99  # liquidate when HF drops below this
    max_repay_fraction: float = 0.5  # repay up to this % of debt per liquidation
    prioritize_by: str = "profit"  # "profit" or "health_factor"


@dataclass
class DepositWithdrawalStrategy:
    """Configuration for depositor withdrawal behavior during stress."""

    enabled: bool = False
    withdrawal_trigger: str = "price_drop"  # "price_drop", "health_factor", "time"
    trigger_threshold: float = 0.10  # withdraw if prices drop >10% or HF <1.1
    withdrawal_rate: float = 0.5  # withdraw this % of deposited amount per block
    block_start: int = 0
    block_end: Optional[int] = None


class RationalLiquidator:
    """
    Liquidator that monitors health factors and executes profitable liquidations.
    """

    def __init__(
        self,
        liquidator_wallet: Wallet,
        env: DefiEnv,
        strategy: LiquidatorStrategy = None,
    ):
        self.wallet = liquidator_wallet
        self.env = env
        self.strategy = strategy or LiquidatorStrategy()
        self.liquidations_executed = 0
        self.total_profit = 0.0

    def step(self) -> None:
        """Execute liquidations based on strategy."""
        if not self.strategy.enabled:
            return

        undercollateralized = [
            w for w in self.env.wallets.values()
            if w.health_factor < self.strategy.target_health_factor and w != self.wallet
        ]

        for borrower in undercollateralized:
            self._attempt_liquidation(borrower)

    def _attempt_liquidation(self, borrower: Wallet) -> None:
        """Attempt to liquidate a borrower."""
        for debt_token, debt_amount in list(borrower.balances.items()):
            # Check if this is a debt token
            if not hasattr(debt_token, 'pool') or debt_amount == 0:
                continue

            pool = debt_token.pool

            # Check if liquidator has funds to repay
            available_balance = self.wallet.balances.get(pool.underlying_token, 0.0)
            if available_balance == 0:
                continue

            # Calculate repay amount
            actual_debt = pool.get_actual_borrow_balance(borrower)
            max_repay = actual_debt * self.strategy.max_repay_fraction
            repay_amount = min(max_repay, available_balance)

            if repay_amount <= 0:
                continue

            try:
                # Find collateral pool (for now, use first available collateral)
                collateral_pools = [
                    p for p in self.env.lending_pools.values()
                    if p.get_actual_supply_balance(borrower) > 0
                ]

                if not collateral_pools:
                    continue

                collateral_pool = collateral_pools[0]

                # Execute liquidation
                pool.liquidate(self.wallet, borrower, repay_amount, collateral_pool)

                self.liquidations_executed += 1
                self.total_profit += repay_amount * pool.underlying_token.price
            except AssertionError:
                continue


class StressDepositWithdrawer:
    """
    Depositor that withdraws during market stress.
    Models bank-run behavior.
    """

    def __init__(
        self,
        depositor_wallet: Wallet,
        env: DefiEnv,
        strategy: DepositWithdrawalStrategy = None,
        price_baseline: dict = None,
    ):
        self.wallet = depositor_wallet
        self.env = env
        self.strategy = strategy or DepositWithdrawalStrategy()
        self.price_baseline = price_baseline or {}
        self.total_withdrawn = 0.0
        self.withdrawals_attempted = 0

    def step(self) -> None:
        """Execute withdrawals based on stress triggers."""
        if not self.strategy.enabled:
            return

        if self.strategy.block_end and self.env.blocknumber > self.strategy.block_end:
            return

        if self.env.blocknumber < self.strategy.block_start:
            return

        if self._should_withdraw():
            self._execute_withdrawal()

    def _should_withdraw(self) -> bool:
        """Determine if withdrawal should be triggered."""
        if self.strategy.withdrawal_trigger == "price_drop":
            return self._check_price_drop()
        elif self.strategy.withdrawal_trigger == "health_factor":
            return self._check_health_factor()
        elif self.strategy.withdrawal_trigger == "time":
            return self.env.blocknumber >= self.strategy.block_start
        return False

    def _check_price_drop(self) -> bool:
        """Check if any asset price has dropped significantly."""
        for token, baseline_price in self.price_baseline.items():
            current_price = self.env.prices.get(token, baseline_price)
            drop = (baseline_price - current_price) / baseline_price
            if drop > self.strategy.trigger_threshold:
                return True
        return False

    def _check_health_factor(self) -> bool:
        """Check if own health factor has dropped below threshold."""
        return self.wallet.health_factor < self.strategy.trigger_threshold

    def _execute_withdrawal(self) -> None:
        """Withdraw supplied assets."""
        for token, balance in list(self.wallet.balances.items()):
            if not hasattr(token, 'pool') or balance == 0:
                continue

            pool = token.pool
            actual_balance = pool.get_actual_supply_balance(self.wallet)

            if actual_balance <= 0:
                continue

            # Withdraw a fraction
            withdraw_amount = actual_balance * self.strategy.withdrawal_rate

            try:
                pool.withdraw(self.wallet, withdraw_amount)
                self.total_withdrawn += withdraw_amount
                self.withdrawals_attempted += 1
            except AssertionError:
                continue


class SimpleAgent:
    """
    Minimal agent that just holds positions and reacts to instructions.
    Base for creating custom agent behaviors.
    """

    def __init__(self, wallet: Wallet, env: DefiEnv):
        self.wallet = wallet
        self.env = env
        self.history = []

    def record_state(self) -> dict:
        """Record current state for analysis."""
        state = {
            'block': self.env.blocknumber,
            'health_factor': self.wallet.health_factor,
            'total_supplied_usd': self.wallet.total_supplied_usd,
            'total_borrowed_usd': self.wallet.total_borrowed_usd,
            'available_collateral_usd': self.wallet.available_collateral_usd,
        }
        self.history.append(state)
        return state
