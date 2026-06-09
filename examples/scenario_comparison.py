"""
Compare multiple scenarios to understand system behavior under different stress.

This demonstrates:
- Running multiple scenarios
- Comparing results across scenarios
- Analyzing relative impact of different market conditions
"""

import sys
sys.path.insert(0, r'c:\Users\gianc\repo\PhD_liquidation_model')

from simulation import ExperimentRunner, ScenarioBuilder


def main():
    builder = ScenarioBuilder()
    runner = ExperimentRunner(builder)

    scenarios = ["simple_test", "mild_stress", "severe_crash", "bank_run"]

    print("=" * 70)
    print("Running scenario comparison")
    print("=" * 70)

    for scenario_name in scenarios:
        config = builder.get_predefined_scenario(scenario_name)
        print(f"\nAdding: {scenario_name}")
        runner.add_experiment(config)

    print(f"\nRunning {len(runner.experiments)} experiments...\n")
    runner.run_all(verbose=True)

    # Compare results
    print("\n" + "=" * 70)
    print("SCENARIO COMPARISON")
    print("=" * 70)

    results = runner.get_results()

    # Create comparison table
    print(f"\n{'Scenario':<20} {'Peak Bad Debt':<18} {'Undercollateralized':<20} {'Liquidations':<15}")
    print("-" * 73)

    for result in results:
        name = result['config']['name']
        summary = result['metrics']['summary']

        peak_debt = summary['peak_bad_debt_usd']
        undercollateralized = summary['peak_undercollateralized']
        liquidations = summary['total_liquidations']

        print(f"{name:<20} ${peak_debt:>15,.2f} {undercollateralized:>19} {liquidations:>14}")

    # Detailed analysis
    print("\n" + "=" * 70)
    print("DETAILED ANALYSIS")
    print("=" * 70)

    for result in results:
        name = result['config']['name']
        summary = result['metrics']['summary']
        agent_stats = result['agent_stats']

        print(f"\n{name.upper()}")
        print(f"  Config: {result['config']['description']}")
        print(f"  Duration: {result['config']['duration_blocks']:,} blocks")
        print(f"\n  System Health:")
        print(f"    Peak bad debt: ${summary['peak_bad_debt_usd']:,.2f}")
        print(f"    Final bad debt: ${summary['final_bad_debt_usd']:,.2f}")
        print(f"    Peak undercollateralized: {summary['peak_undercollateralized']}")
        print(f"    Min health factor: {summary['min_health_factor']:.4f}")
        print(f"    Total liquidations: {summary['total_liquidations']}")

        if agent_stats['liquidators']:
            print(f"\n  Liquidator Activity:")
            for liq_name, stats in agent_stats['liquidators'].items():
                print(f"    {liq_name}:")
                print(f"      Liquidations: {stats['liquidations_executed']}")
                print(f"      Profit: ${stats['total_profit']:,.2f}")

        if agent_stats['withdrawers']:
            print(f"\n  Withdrawal Activity:")
            for with_name, stats in agent_stats['withdrawers'].items():
                print(f"    {with_name}:")
                print(f"      Total withdrawn: ${stats['total_withdrawn']:,.2f}")
                print(f"      Attempts: {stats['withdrawal_attempts']}")


if __name__ == "__main__":
    main()
