"""
Simple example: Run a basic scenario and examine results.

This demonstrates:
- Creating a simple scenario
- Running an experiment
- Extracting and analyzing metrics
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from simulation import Experiment, ScenarioBuilder


def main():
    # Get a pre-built simple scenario
    builder = ScenarioBuilder()
    config = builder.get_predefined_scenario("simple_test")

    print("=" * 70)
    print(f"Scenario: {config.name}")
    print(f"Description: {config.description}")
    print(f"Duration: {config.duration_blocks} blocks (~1 year)")
    print("=" * 70)

    # Create and run experiment
    experiment = Experiment(config, builder)
    experiment.setup()

    print("\nInitial state:")
    for wallet_name, wallet in experiment.env.wallets.items():
        print(f"  {wallet_name}: {wallet.balances}")

    print("\nRunning simulation...")
    experiment.run(verbose=True)

    # Get results
    results = experiment.get_results()
    summary = results['metrics']['summary']

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    print(f"\nSystem Metrics:")
    print(f"  Peak bad debt: ${summary['peak_bad_debt_usd']:.2f}")
    print(f"  Final bad debt: ${summary['final_bad_debt_usd']:.2f}")
    print(f"  Peak undercollateralized users: {summary['peak_undercollateralized']}")
    print(f"  Minimum health factor: {summary['min_health_factor']:.4f}")
    print(f"  Total liquidations: {summary['total_liquidations']}")

    print(f"\nAgent Statistics:")
    for liquidator_name, stats in results['agent_stats']['liquidators'].items():
        print(f"  {liquidator_name}:")
        print(f"    Liquidations executed: {stats['liquidations_executed']}")
        print(f"    Total profit: ${stats['total_profit']:.2f}")

    print(f"\nPool Metrics (final state):")
    pool_metrics = results['metrics']['pools']
    for pool_name, metrics in pool_metrics.items():
        print(f"  {pool_name}:")
        print(f"    Available liquidity: {metrics['available_liquidity'][-1]:,.2f}")
        print(f"    Total supply: {metrics['total_supply'][-1]:,.2f}")
        print(f"    Total borrow: {metrics['total_borrow'][-1]:,.2f}")
        print(f"    Usage ratio: {metrics['usage_ratio'][-1]:.4f}")
        print(f"    Bad debt: {metrics['bad_debt'][-1]:,.2f}")


if __name__ == "__main__":
    main()
