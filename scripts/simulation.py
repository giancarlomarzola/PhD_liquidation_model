from __future__ import annotations
from dataclasses import dataclass
from environment.defi_env import DefiEnv, Wallet, Token, aToken, vToken, LendingPool  # noqa: F401
from environment.parameters import pool_parameters


class Simulation:
    def __init__(
        self,
        environment: DefiEnv,
        agents: list[Agent]
        # other parameters? e.g.
        # Agent strategies and amounts
        # Simulation duration

    ):
        self.environment = environment
        self.agents = agents


@dataclass
class DepositWithdrawalStrategy:
    """Configuration for agent deposit and withdrawal behavior."""
    withdrawal_trigger: str = "price"  # "price_change", "health_factor", "time"
    withdrawal_trigger_threshold: float = 0.10  # withdraw if prices change >10% or HF <1.1
    withdrawal_rate: float = 0.5  # withdraw this % of deposited amount per block
    deposit_trigger: str = "price"  # "price_change", "health_factor", "time"
    deposit_trigger_threshold: float = 0.10
    deposit_rate: float = 0.05


@dataclass
class LiquidatorStrategy:
    """Configuration for liquidator behavior."""
    target_health_factor: float = 0.99  # liquidate when HF drops below this
    max_repay_fraction: float = 0.5  # repay up to this % of debt per liquidation
    prioritize_by: str = "profit"  # "profit" or "health_factor"



class Agent:
    """
    Minimal agent that just holds positions and reacts to instructions.
    Base for creating custom agent behaviors.
    """

    def __init__(
        self, 
        name: str,
        env: DefiEnv,
        strategy: DepositWithdrawalStrategy,
        wallet: Wallet = None, 
        liquidator_strategy: LiquidatorStrategy | None = None,
        initial_endowment: dict[Token, float] | None = None
    ):
        self.env = env
        self.name = name
        self.history = []
        self.strategy = strategy or DepositWithdrawalStrategy() # use default values if not specified
        self.liquidator_strategy = liquidator_strategy
        
        self.wallet = wallet or Wallet(env, name, None)

        if initial_endowment:
            for token, amount in initial_endowment:
                token.mint(self.wallet, amount)

    def _strategy_transaction_amount(self):
        # use strategy and environment properties to determine transactions the Agent executes
        pass

    def enact_strategy(self):
        # first determine strategy dictated amounts and pools
        # Also any additional/manual transaction amounts
        # Then carry out transactions
        self.wallet.supply() # etc.
        pass

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

    # 1: set up market env with tokens and pools allowed
    defi_env = DefiEnv(prices={"usdc": 1.00, "wbtc": 50_000.00})

    usdc = Token(defi_env, "usdc")
    wbtc = Token(defi_env, "wbtc")

    usdc_pool = LendingPool(
        env=defi_env, underlying_token=usdc, **pool_parameters["usdc"]
    )
    wbtc_pool = LendingPool(
        env=defi_env, underlying_token=wbtc, **pool_parameters["wbtc"]
    )

    # 2: define strategies
    # placeholder strategies

    interest_seeker = DepositWithdrawalStrategy(
        # Need to find a way to make them find pools with highest interest
        # maybe something like "interest" trigger where withdrawals and depositis are 
        # triggered by difference between current pools and best pools
        withdrawal_trigger="interest",
        withdrawal_trigger_threshold=0.1,

    )

    # deposits periodically and withdraws heavily in a crash
    panic_withdrawer = DepositWithdrawalStrategy(
        withdrawal_trigger="health_factor",
        withdrawal_trigger_threshold=0.15,
        withdrawal_rate=0.4,
        deposit_trigger="time",
        deposit_trigger_threshold=50, # should then be deposit every 50 blocks
        deposit_rate=0.1,
    )

    # Withdraws when price increases and deposits when price decreases
    contrarian = DepositWithdrawalStrategy(
        withdrawal_trigger="price",
        withdrawal_trigger_threshold=0.02,
        withdrawal_rate=0.1,
        deposit_trigger="price",
        deposit_trigger_threshold=-0.02,
        deposit_rate=0.1,
    )


    # Set up simulation 
    simulation = Simulation(defi_env, agents=[])


    # 3: create agents with different strategies
    num_contrarian_agents = 100
    for i in num_contrarian_agents:
        simulation.agents.append(
            Agent(
                name=f"contrarian{i}",
                defi_env=defi_env,
                strategy=contrarian,
                liquidator_strategy=None,
                wallet=None,
                initial_endowment={wbtc:1, usdc:20_000} # maybe randomize a bit
            )
        )

    num_panic_agents = 100
    for i in num_panic_agents:
        simulation.agents.append(
            Agent(
                name=f"panic_{i}",
                defi_env=simulation.defi_env,
                strategy=panic_withdrawer,
                liquidator_strategy=None,
                wallet=None,
                initial_endowment={wbtc:1, usdc:20_000}
            )
        )

    num_liquidator_agents = 10
    for i in num_liquidator_agents:
        simulation.agents.append(
            Agent(
                name=f"liquidator_{i}",
                defi_env=simulation.defi_env,
                strategy=panic_withdrawer,
                liquidator_strategy=LiquidatorStrategy(),
                wallet=None,
                initial_endowment={wbtc:1, usdc:20_000}
            )
        )