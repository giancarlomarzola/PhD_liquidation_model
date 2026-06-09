"""Scenario definitions and scenario builder."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from environment.defi_env import DefiEnv, Token, Wallet, LendingPool
from simulation.price_providers import PriceProvider
from simulation.agents import RationalLiquidator, StressDepositWithdrawer
from simulation.agents import LiquidatorStrategy, DepositWithdrawalStrategy


@dataclass
class InitialMarketState:
    """Definition of initial market state."""

    tokens: Dict[str, float]  # token_symbol -> initial_price
    pools: Dict[str, Dict]  # pool_symbol -> pool_parameters
    wallets: Dict[str, Dict]  # wallet_name -> wallet_config


@dataclass
class ScenarioConfig:
    """Configuration for a simulation scenario."""

    name: str
    description: str = ""
    initial_market_state: InitialMarketState = None
    price_provider: PriceProvider = None
    duration_blocks: int = 100
    liquidators: Dict[str, LiquidatorStrategy] = field(default_factory=dict)
    depositors: Dict[str, DepositWithdrawalStrategy] = field(default_factory=dict)
    step_callback: Optional[Callable[[DefiEnv], None]] = None


class ScenarioBuilder:
    """Helper to construct and run scenarios."""

    def __init__(self, pool_parameters: Dict = None):
        """
        Parameters
        ----------
        pool_parameters : dict, optional
            Reference parameters for pools (e.g., from environment.parameters)
        """
        self.pool_parameters = pool_parameters or {}

    def build_env(self, config: ScenarioConfig) -> DefiEnv:
        """Build a DefiEnv from scenario config."""
        env = DefiEnv(price_provider=config.price_provider)

        # Create tokens and set initial prices
        for token_symbol, price in config.initial_market_state.tokens.items():
            Token(env, token_symbol)
            env.prices[token_symbol] = price

        # Create pools
        for pool_symbol, pool_params in config.initial_market_state.pools.items():
            underlying_token = env.tokens[pool_symbol]
            LendingPool(env, underlying_token, **pool_params)

        # Create wallets and populate with initial balances
        for wallet_name, wallet_config in config.initial_market_state.wallets.items():
            wallet = Wallet(env, wallet_name, is_liquidator=wallet_config.get('is_liquidator', False))

            # Mint initial token balances
            for token_symbol, balance in wallet_config.get('balances', {}).items():
                token = env.tokens[token_symbol]
                token.mint(wallet, balance)

        return env

    def get_predefined_scenario(self, scenario_name: str) -> ScenarioConfig:
        """Get a predefined scenario by name."""
        if scenario_name == "simple_test":
            return self._scenario_simple_test()
        elif scenario_name == "mild_stress":
            return self._scenario_mild_stress()
        elif scenario_name == "severe_crash":
            return self._scenario_severe_crash()
        elif scenario_name == "bank_run":
            return self._scenario_bank_run()
        else:
            raise ValueError(f"Unknown scenario: {scenario_name}")

    def _scenario_simple_test(self) -> ScenarioConfig:
        """Simple scenario: Alice deposits USDC, Bob borrows against WBTC."""
        from simulation.price_providers import MockPriceProvider

        initial_state = InitialMarketState(
            tokens={"usdc": 1.0, "wbtc": 50_000.0},
            pools={
                "usdc": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.8,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.83,
                    "closing_factor": 0.5,
                },
                "wbtc": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.73,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.78,
                    "closing_factor": 0.5,
                },
            },
            wallets={
                "alice": {
                    "is_liquidator": True,
                    "balances": {"usdc": 100_000},
                },
                "bob": {
                    "is_liquidator": False,
                    "balances": {"wbtc": 2.0},
                },
            },
        )

        return ScenarioConfig(
            name="simple_test",
            description="Basic setup: Alice supplies USDC, Bob borrows against WBTC",
            initial_market_state=initial_state,
            price_provider=MockPriceProvider({"usdc": 1.0, "wbtc": 50_000.0}),
            duration_blocks=2_628_000,  # 1 year
            liquidators={"alice": LiquidatorStrategy(enabled=True)},
        )

    def _scenario_mild_stress(self) -> ScenarioConfig:
        """Mild stress: 10% price drop over months."""
        from simulation.price_providers import MockPriceProvider

        initial_prices = {"usdc": 1.0, "wbtc": 50_000.0, "eth": 3_000.0}

        price_shocks = {}
        blocks_per_month = 2_628_000 / 12
        target_price = 45_000.0
        price_diff_per_block = (target_price - 50_000.0) / (2 * blocks_per_month)

        current_price = 50_000.0
        for block in range(100_000, 300_000):
            current_price += price_diff_per_block
            price_shocks[block] = {"wbtc": current_price}

        initial_state = InitialMarketState(
            tokens=initial_prices,
            pools={
                "usdc": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.8,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.83,
                    "closing_factor": 0.5,
                },
                "wbtc": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.73,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.78,
                    "closing_factor": 0.5,
                },
                "eth": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.75,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.8,
                    "closing_factor": 0.5,
                },
            },
            wallets={
                "liquidator": {
                    "is_liquidator": True,
                    "balances": {"usdc": 500_000},
                },
                "user_1": {
                    "is_liquidator": False,
                    "balances": {"wbtc": 5.0, "usdc": 50_000},
                },
                "user_2": {
                    "is_liquidator": False,
                    "balances": {"eth": 20.0, "usdc": 30_000},
                },
            },
        )

        return ScenarioConfig(
            name="mild_stress",
            description="10% price drop over 2 months",
            initial_market_state=initial_state,
            price_provider=MockPriceProvider(initial_prices, price_shocks),
            duration_blocks=400_000,
            liquidators={"liquidator": LiquidatorStrategy(enabled=True)},
        )

    def _scenario_severe_crash(self) -> ScenarioConfig:
        """Severe crash: 50% drop in hours."""
        from simulation.price_providers import MockPriceProvider

        initial_prices = {"usdc": 1.0, "wbtc": 50_000.0, "eth": 3_000.0}
        crash_start = 10_000
        crash_end = 15_000

        price_shocks = {}
        for block in range(crash_start, crash_end):
            progress = (block - crash_start) / (crash_end - crash_start)
            wbtc_price = 50_000.0 * (1 - 0.5 * progress)
            eth_price = 3_000.0 * (1 - 0.4 * progress)
            price_shocks[block] = {"wbtc": wbtc_price, "eth": eth_price}

        initial_state = InitialMarketState(
            tokens=initial_prices,
            pools={
                "usdc": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.8,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.83,
                    "closing_factor": 0.5,
                },
                "wbtc": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.73,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.78,
                    "closing_factor": 0.5,
                },
                "eth": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.75,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.8,
                    "closing_factor": 0.5,
                },
            },
            wallets={
                "liquidator": {
                    "is_liquidator": True,
                    "balances": {"usdc": 1_000_000},
                },
                "user_1": {
                    "is_liquidator": False,
                    "balances": {"wbtc": 10.0, "usdc": 100_000},
                },
                "user_2": {
                    "is_liquidator": False,
                    "balances": {"eth": 50.0, "usdc": 60_000},
                },
                "user_3": {
                    "is_liquidator": False,
                    "balances": {"wbtc": 5.0, "eth": 30.0},
                },
            },
        )

        return ScenarioConfig(
            name="severe_crash",
            description="50% BTC crash + 40% ETH drop in 5000 blocks",
            initial_market_state=initial_state,
            price_provider=MockPriceProvider(initial_prices, price_shocks),
            duration_blocks=50_000,
            liquidators={"liquidator": LiquidatorStrategy(enabled=True)},
        )

    def _scenario_bank_run(self) -> ScenarioConfig:
        """Bank-run: large-scale deposits followed by panic withdrawals."""
        from simulation.price_providers import MockPriceProvider

        initial_prices = {"usdc": 1.0, "dai": 1.0, "usdt": 1.0}

        initial_state = InitialMarketState(
            tokens=initial_prices,
            pools={
                "usdc": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.8,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.83,
                    "closing_factor": 0.5,
                    "supply_cap": 5_000_000,
                },
                "dai": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.75,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.78,
                    "closing_factor": 0.5,
                    "supply_cap": 3_000_000,
                },
                "usdt": {
                    "interest_slope_1": 0.04,
                    "interest_slope_2": 0.60,
                    "interest_base_rate": 0.0,
                    "optimal_usage_ratio": 0.9,
                    "reserve_rate": 0.1,
                    "max_ltv": 0.80,
                    "liquidation_bonus": 0.05,
                    "liquidation_threshold": 0.85,
                    "closing_factor": 0.5,
                    "supply_cap": 4_000_000,
                },
            },
            wallets={
                "lp_1": {
                    "is_liquidator": False,
                    "balances": {"usdc": 2_000_000},
                },
                "lp_2": {
                    "is_liquidator": False,
                    "balances": {"dai": 1_500_000},
                },
                "lp_3": {
                    "is_liquidator": False,
                    "balances": {"usdt": 1_800_000},
                },
            },
        )

        return ScenarioConfig(
            name="bank_run",
            description="Stablecoin liquidity crisis with withdrawal panic",
            initial_market_state=initial_state,
            price_provider=MockPriceProvider(initial_prices),
            duration_blocks=200_000,
            depositors={
                "lp_1": DepositWithdrawalStrategy(
                    enabled=True,
                    withdrawal_trigger="time",
                    block_start=50_000,
                    withdrawal_rate=0.3,
                ),
                "lp_2": DepositWithdrawalStrategy(
                    enabled=True,
                    withdrawal_trigger="time",
                    block_start=50_000,
                    withdrawal_rate=0.3,
                ),
                "lp_3": DepositWithdrawalStrategy(
                    enabled=True,
                    withdrawal_trigger="time",
                    block_start=50_000,
                    withdrawal_rate=0.3,
                ),
            },
        )
