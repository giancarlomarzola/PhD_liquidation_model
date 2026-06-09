"""Experiment runner and simulation execution."""

from typing import List, Dict, Optional
from environment.defi_env import DefiEnv, Wallet
from simulation.scenarios import ScenarioConfig, ScenarioBuilder
from simulation.agents import RationalLiquidator, StressDepositWithdrawer
from simulation.metrics import MetricsCollector


class Experiment:
    """Run a complete simulation experiment."""

    def __init__(self, config: ScenarioConfig, scenario_builder: ScenarioBuilder = None):
        """
        Parameters
        ----------
        config : ScenarioConfig
            Scenario configuration
        scenario_builder : ScenarioBuilder, optional
            Builder for constructing environments. If None, creates default.
        """
        self.config = config
        self.scenario_builder = scenario_builder or ScenarioBuilder()
        self.env = None
        self.metrics = None
        self.liquidators: Dict[str, RationalLiquidator] = {}
        self.withdrawers: Dict[str, StressDepositWithdrawer] = {}

    def setup(self) -> None:
        """Initialize environment and agents."""
        self.env = self.scenario_builder.build_env(self.config)
        self.metrics = MetricsCollector(self.env)

        # Setup liquidators
        for liquidator_name, strategy in self.config.liquidators.items():
            if liquidator_name in self.env.wallets:
                wallet = self.env.wallets[liquidator_name]
                liquidator = RationalLiquidator(wallet, self.env, strategy)
                self.liquidators[liquidator_name] = liquidator

        # Setup depositors with withdrawal strategies
        price_baseline = self.config.initial_market_state.tokens.copy()
        for depositor_name, strategy in self.config.depositors.items():
            if depositor_name in self.env.wallets:
                wallet = self.env.wallets[depositor_name]
                withdrawer = StressDepositWithdrawer(wallet, self.env, strategy, price_baseline)
                self.withdrawers[depositor_name] = withdrawer

    def run(self, verbose: bool = False) -> None:
        """Run the simulation."""
        if self.env is None:
            self.setup()

        if verbose:
            print(f"Running scenario: {self.config.name}")
            print(f"Duration: {self.config.duration_blocks} blocks")

        for block in range(self.config.duration_blocks):
            # Execute agent step functions
            for liquidator in self.liquidators.values():
                liquidator.step()

            for withdrawer in self.withdrawers.values():
                withdrawer.step()

            # Optional step callback (for custom behavior)
            if self.config.step_callback:
                self.config.step_callback(self.env)

            # Record metrics
            self.metrics.record_step()

            # Advance environment
            self.env.advance_blocks(1)

            if verbose and (block + 1) % (self.config.duration_blocks // 10) == 0:
                progress = (block + 1) / self.config.duration_blocks * 100
                print(f"  {progress:.0f}% complete (block {block + 1})")

        if verbose:
            print("Simulation complete")

    def get_results(self) -> dict:
        """Get simulation results."""
        return {
            'config': {
                'name': self.config.name,
                'description': self.config.description,
                'duration_blocks': self.config.duration_blocks,
            },
            'metrics': self.metrics.to_dict(),
            'agent_stats': {
                'liquidators': {
                    name: {
                        'liquidations_executed': agent.liquidations_executed,
                        'total_profit': agent.total_profit,
                    }
                    for name, agent in self.liquidators.items()
                },
                'withdrawers': {
                    name: {
                        'total_withdrawn': agent.total_withdrawn,
                        'withdrawal_attempts': agent.withdrawals_attempted,
                    }
                    for name, agent in self.withdrawers.items()
                },
            },
        }


class ExperimentRunner:
    """Run multiple experiments with parameter sweeps."""

    def __init__(self, scenario_builder: ScenarioBuilder = None):
        self.scenario_builder = scenario_builder or ScenarioBuilder()
        self.experiments: List[Experiment] = []
        self.results: List[dict] = []

    def add_experiment(self, config: ScenarioConfig) -> None:
        """Add an experiment to the queue."""
        exp = Experiment(config, self.scenario_builder)
        self.experiments.append(exp)

    def run_all(self, verbose: bool = False) -> None:
        """Run all queued experiments."""
        for i, experiment in enumerate(self.experiments):
            if verbose:
                print(f"\n[{i+1}/{len(self.experiments)}] {experiment.config.name}")
                print("=" * 60)

            experiment.setup()
            experiment.run(verbose=verbose)
            self.results.append(experiment.get_results())

    def get_results(self) -> List[dict]:
        """Get all experiment results."""
        return self.results

    def compare_experiments(self, metric_name: str = "peak_bad_debt_usd") -> Dict[str, float]:
        """Compare a metric across all experiments."""
        comparison = {}
        for result in self.results:
            name = result['config']['name']
            value = result['metrics']['summary'].get(metric_name, None)
            comparison[name] = value
        return comparison


def run_scenario(scenario_name: str, scenario_builder: ScenarioBuilder = None, verbose: bool = True) -> dict:
    """Convenience function to run a predefined scenario."""
    if scenario_builder is None:
        scenario_builder = ScenarioBuilder()

    config = scenario_builder.get_predefined_scenario(scenario_name)
    experiment = Experiment(config, scenario_builder)
    experiment.setup()
    experiment.run(verbose=verbose)

    return experiment.get_results()
