"""
Example: Load empirical Aave data and run simulation.

This demonstrates:
- Loading historical price data from parquet files (filtered by block range and tokens)
- Inspecting available data
- Running simulation with real market prices
"""

import sys
from pathlib import Path

# Make imports relative to project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from simulation import (
    EmpiricalPriceProvider,
    ScenarioConfig,
    InitialMarketState,
    ScenarioBuilder,
    Experiment,
    LiquidatorStrategy,
)


def main():
    print("=" * 70)
    print("Loading empirical Aave data...")
    print("=" * 70)

    # Load empirical price data
    # For testing, load only a subset of available blocks to reduce memory usage
    # Available block range: 20,921,766 to 20,949,543
    try:
        provider = EmpiricalPriceProvider(
            tokens=["WETH", "WBTC", "USDC", "DAI", "LINK", "AAVE"],
            start_block=20_921_766,
            end_block=20_924_500,
        )

        print("\n[OK] Data loaded successfully")
        print(f"  Available tokens: {provider.get_available_tokens()}")
        min_block, max_block = provider.get_block_range()
        print(f"  Block range: {min_block:,} to {max_block:,}")
        print(f"  Total blocks: {max_block - min_block:,}")

        # Get initial prices
        initial_prices = provider.get_prices()
        print(f"\n  Initial prices:")
        for symbol, price in sorted(initial_prices.items()):
            print(f"    {symbol}: ${price:,.2f}")

    except Exception as e:
        print(f"[ERROR] Failed to load data: {e}")
        print("\nNote: This example requires empirical data in ./data/aave_parquet/")
        print(
            "You can adjust start_block and end_block parameters to load different block ranges."
        )
        return

    # Create a scenario with empirical prices
    initial_state = InitialMarketState(
        tokens=initial_prices,
        pools={
            "USDC": {
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
            "WETH": {
                "interest_slope_1": 0.04,
                "interest_slope_2": 0.60,
                "interest_base_rate": 0.0,
                "optimal_usage_ratio": 0.9,
                "reserve_rate": 0.1,
                "max_ltv": 0.825,
                "liquidation_bonus": 0.05,
                "liquidation_threshold": 0.86,
                "closing_factor": 0.5,
            },
            "WBTC": {
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
            "lp_usdc": {
                "is_liquidator": False,
                "balances": {"USDC": 5_000_000},
            },
            "trader_eth": {
                "is_liquidator": False,
                "balances": {"WETH": 100},
            },
            "arbitrageur": {
                "is_liquidator": True,
                "balances": {"USDC": 1_000_000},
            },
        },
    )

    # Run simulation for the full duration of loaded data
    duration_blocks = max_block - min_block

    config = ScenarioConfig(
        name="empirical_aave_replay",
        description="Replay recent Aave market with empirical price data",
        initial_market_state=initial_state,
        price_provider=provider,
        duration_blocks=duration_blocks,
        liquidators={"arbitrageur": LiquidatorStrategy(enabled=True)},
    )

    print("\n" + "=" * 70)
    print("Running simulation with empirical prices...")
    print("=" * 70)

    builder = ScenarioBuilder()
    experiment = Experiment(config, builder)
    experiment.setup()
    experiment.run(verbose=True)

    # Analyze results
    results = experiment.get_results()
    summary = results["metrics"]["summary"]

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    print(f"\nSystem Health:")
    print(f"  Peak bad debt: ${summary['peak_bad_debt_usd']:,.2f}")
    print(f"  Final bad debt: ${summary['final_bad_debt_usd']:,.2f}")
    print(f"  Peak undercollateralized: {summary['peak_undercollateralized']}")
    print(f"  Minimum health factor: {summary['min_health_factor']:.4f}")
    print(f"  Total liquidations: {summary['total_liquidations']}")

    if summary["total_liquidations"] > 0:
        print("\n  [WARNING] Undercollateralization events detected!")
        print(f"    {summary['total_liquidations']} liquidation(s) occurred")
        print(
            f"    Peak undercollateralized users: {summary['peak_undercollateralized']}"
        )


if __name__ == "__main__":
    main()
