# DeFi Lending Simulation Environment - Setup Guide

## Overview

This simulation framework models DeFi lending protocols (Aave-style) to research liquidity risk, bad debt accumulation, and cascade effects. It is designed to support research on the paper: "Liquidity Risk in DeFi Lending Protocols".

### Core Design Principles

1. **Modular Price Sources**: Price data can come from:
   - Empirical historical data (Aave parquet files in `data/aave_parquet/`)
   - Stochastic processes (simulated price movements)
   - Mock prices (for testing and controlled experiments)

2. **Agent-Based Simulation**: Agents (liquidators, depositors) act based on configurable strategies

3. **Comprehensive Metrics**: Track pool-level and system-level risk metrics

4. **Scenario-Driven**: Pre-built scenarios for common stress conditions (mild stress, severe crash, bank runs)

---

## Architecture

### 1. Price Providers (`simulation/price_providers.py`)

**Purpose**: Abstract away price source. Easy to swap implementations.

#### MockPriceProvider
For testing and controlled experiments.

```python
from simulation import MockPriceProvider

# Fixed prices
provider = MockPriceProvider({"usdc": 1.0, "wbtc": 50_000})

# With price shocks at specific blocks
price_shocks = {
    1000: {"wbtc": 45_000},  # WBTC drops to 45k at block 1000
    2000: {"wbtc": 40_000},  # Further drop to 40k at block 2000
}
provider = MockPriceProvider({"usdc": 1.0, "wbtc": 50_000}, price_shocks)
```

#### StochasticPriceProvider
Generate prices using geometric Brownian motion (for stress testing).

```python
from simulation import StochasticPriceProvider

provider = StochasticPriceProvider(
    initial_prices={"usdc": 1.0, "wbtc": 50_000, "eth": 3_000},
    volatilities={"usdc": 0.01, "wbtc": 0.3, "eth": 0.35},
    drifts={"usdc": 0.0, "wbtc": -0.05, "eth": -0.05},  # downward drift for stress
    random_seed=42
)
```

#### EmpiricalPriceProvider
Load actual historical Aave data.

```python
from simulation import EmpiricalPriceProvider

# Reads from data/aave_parquet/*.parquet
provider = EmpiricalPriceProvider(
    tokens=["WETH", "WBTC", "USDC", "DAI"],  # tokens to load
    resample_blocks=1  # sample every 1 block (or more to skip blocks)
)
available_tokens = provider.get_available_tokens()
min_block, max_block = provider.get_block_range()
```

---

### 2. Scenario Builder (`simulation/scenarios.py`)

**Purpose**: Define market states and simulation parameters.

#### Creating a Custom Scenario

```python
from simulation import ScenarioConfig, InitialMarketState, ScenarioBuilder
from simulation import MockPriceProvider, LiquidatorStrategy

initial_state = InitialMarketState(
    tokens={"usdc": 1.0, "wbtc": 50_000, "eth": 3_000},
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
            # ... similar structure
        },
        "eth": {
            # ... similar structure
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

config = ScenarioConfig(
    name="my_custom_scenario",
    description="Custom stress test scenario",
    initial_market_state=initial_state,
    price_provider=MockPriceProvider({"usdc": 1.0, "wbtc": 50_000, "eth": 3_000}),
    duration_blocks=500_000,
    liquidators={"liquidator": LiquidatorStrategy(enabled=True)},
)
```

#### Using Pre-built Scenarios

```python
from simulation import ScenarioBuilder

builder = ScenarioBuilder()
config = builder.get_predefined_scenario("simple_test")  # or "mild_stress", "severe_crash", "bank_run"
```

---

### 3. Agents (`simulation/agents.py`)

**Purpose**: Model participant behavior during simulation.

#### RationalLiquidator
Monitors health factors and executes liquidations.

```python
from simulation import RationalLiquidator, LiquidatorStrategy

strategy = LiquidatorStrategy(
    enabled=True,
    target_health_factor=0.99,  # liquidate when HF < 0.99
    max_repay_fraction=0.5,      # repay up to 50% of debt
    prioritize_by="profit",      # liquidate most profitable first
)

liquidator = RationalLiquidator(liquidator_wallet, env, strategy)
liquidator.step()  # called each block during simulation

# Check results
print(f"Liquidations: {liquidator.liquidations_executed}")
print(f"Total profit: ${liquidator.total_profit:.2f}")
```

#### StressDepositWithdrawer
Models bank-run behavior / stress withdrawals.

```python
from simulation import StressDepositWithdrawer, DepositWithdrawalStrategy

strategy = DepositWithdrawalStrategy(
    enabled=True,
    withdrawal_trigger="price_drop",      # trigger on price drops
    trigger_threshold=0.10,               # withdraw if >10% drop
    withdrawal_rate=0.5,                  # withdraw 50% per block
    block_start=100_000,
    block_end=200_000,
)

withdrawer = StressDepositWithdrawer(depositor_wallet, env, strategy, price_baseline)
withdrawer.step()  # called each block

print(f"Total withdrawn: ${withdrawer.total_withdrawn:.2f}")
```

---

### 4. Metrics Collector (`simulation/metrics.py`)

**Purpose**: Track risk metrics during simulation.

```python
from simulation import MetricsCollector

collector = MetricsCollector(env)

# During simulation loop
for block in range(duration):
    # ... agent steps ...
    env.advance_blocks(1)
    collector.record_step()

# Get summary statistics
summary = collector.get_system_summary()
print(f"Peak bad debt: ${summary['peak_bad_debt_usd']:.2f}")
print(f"Peak undercollateralized users: {summary['peak_undercollateralized']}")
print(f"Total liquidations: {summary['total_liquidations']}")

# Export all metrics
results = collector.to_dict()
```

#### Available Metrics

**Pool-level** (per pool):
- `available_liquidity`: Cash available in pool
- `total_supply` / `total_borrow`: Amount of assets
- `usage_ratio`: Borrow / (Borrow + Liquidity)
- `borrow_rate` / `supply_rate`: Interest rates
- `bad_debt`: Unrecoverable debt
- `supply_index` / `borrow_index`: Interest accrual indices

**System-level**:
- `total_bad_debt_usd`: Aggregate bad debt across pools
- `num_undercollateralized_users`: Count of HF < 1
- `max_health_factor_risk`: Minimum HF in system (most at-risk user)
- `liquidation_count`: Total liquidations executed

---

### 5. Experiment Runner (`simulation/experiment.py`)

**Purpose**: Execute and manage simulations.

#### Running a Single Experiment

```python
from simulation import Experiment, ScenarioBuilder

builder = ScenarioBuilder()
config = builder.get_predefined_scenario("mild_stress")

experiment = Experiment(config, builder)
experiment.setup()
experiment.run(verbose=True)

results = experiment.get_results()
print(results['metrics']['summary'])
```

#### Running Multiple Experiments (Sweep)

```python
from simulation import ExperimentRunner

runner = ExperimentRunner()

# Queue multiple scenarios
runner.add_experiment(builder.get_predefined_scenario("simple_test"))
runner.add_experiment(builder.get_predefined_scenario("mild_stress"))
runner.add_experiment(builder.get_predefined_scenario("severe_crash"))
runner.add_experiment(builder.get_predefined_scenario("bank_run"))

# Run all
runner.run_all(verbose=True)

# Compare results
peak_bad_debts = runner.compare_experiments("peak_bad_debt_usd")
print(peak_bad_debts)
```

#### Convenience Function

```python
from simulation import run_scenario

results = run_scenario("severe_crash", verbose=True)
```

---

## Example: Complete Workflow

```python
from simulation import (
    MockPriceProvider, ScenarioConfig, InitialMarketState,
    LiquidatorStrategy, DepositWithdrawalStrategy,
    Experiment, ScenarioBuilder
)

# 1. Define price movement (crash from 50k to 25k over 50k blocks)
price_shocks = {}
for block in range(10_000, 60_000):
    progress = (block - 10_000) / 50_000
    btc_price = 50_000 * (1 - 0.5 * progress)  # linear drop to 25k
    price_shocks[block] = {"wbtc": btc_price}

provider = MockPriceProvider(
    {"usdc": 1.0, "wbtc": 50_000},
    price_shocks
)

# 2. Create initial market state
initial_state = InitialMarketState(
    tokens={"usdc": 1.0, "wbtc": 50_000},
    pools={
        "usdc": {...},  # pool parameters
        "wbtc": {...},
    },
    wallets={
        "lp": {"is_liquidator": False, "balances": {"usdc": 1_000_000}},
        "trader": {"is_liquidator": False, "balances": {"wbtc": 10.0}},
        "liquidator": {"is_liquidator": True, "balances": {"usdc": 500_000}},
    },
)

# 3. Create scenario
config = ScenarioConfig(
    name="btc_crash_test",
    description="BTC drops 50% in 50k blocks",
    initial_market_state=initial_state,
    price_provider=provider,
    duration_blocks=100_000,
    liquidators={"liquidator": LiquidatorStrategy(enabled=True)},
)

# 4. Run experiment
builder = ScenarioBuilder()
experiment = Experiment(config, builder)
experiment.setup()
experiment.run(verbose=True)

# 5. Analyze results
results = experiment.get_results()
summary = results['metrics']['summary']

print(f"\nResults:")
print(f"  Peak bad debt: ${summary['peak_bad_debt_usd']:.2f}")
print(f"  Final bad debt: ${summary['final_bad_debt_usd']:.2f}")
print(f"  Max undercollateralized: {summary['peak_undercollateralized']}")
print(f"  Total liquidations: {summary['total_liquidations']}")
```

---

## Connecting to Empirical Data

To use actual Aave market data:

```python
from simulation import EmpiricalPriceProvider

provider = EmpiricalPriceProvider(
    data_dir=r"c:\Users\gianc\repo\PhD_liquidation_model\data\aave_parquet",
    tokens=["WETH", "WBTC", "USDC", "DAI", "LINK"],
)

# Query available data
available_tokens = provider.get_available_tokens()
min_block, max_block = provider.get_block_range()

print(f"Available tokens: {available_tokens}")
print(f"Block range: {min_block} to {max_block}")

# Use in scenario
config = ScenarioConfig(
    name="empirical_test",
    initial_market_state=initial_state,
    price_provider=provider,
    duration_blocks=min(100_000, max_block - min_block),
)
```

---

## Extending the Framework

### Custom Agent Behavior

```python
from simulation import SimpleAgent

class MyCustomAgent(SimpleAgent):
    def step(self):
        # Your custom logic
        if self.wallet.health_factor < 1.2:
            # Do something
            pass
        
        # Record state at each step
        self.record_state()
```

### Custom Metrics

```python
from simulation import MetricsCollector

class CustomMetricsCollector(MetricsCollector):
    def record_step(self):
        super().record_step()
        
        # Add custom tracking
        for wallet in self.env.wallets.values():
            # Custom logic
            pass
```

---

## File Structure

```
simulation/
├── __init__.py                # Package exports
├── price_providers.py         # Price source abstraction
├── agents.py                  # Agent behavior models
├── scenarios.py               # Scenario definitions
├── metrics.py                 # Metrics tracking
├── experiment.py              # Experiment runner
└── examples/
    ├── simple_test.py
    ├── empirical_analysis.py
    └── parameter_sweep.py
```

---

## Next Steps

1. **Start with a simple scenario** (`run_scenario("simple_test")`)
2. **Experiment with parameter variations** (pool parameters, agent strategies)
3. **Load empirical data** and validate against real Aave events
4. **Design custom scenarios** based on research questions
5. **Run parameter sweeps** to answer "what-if" questions
