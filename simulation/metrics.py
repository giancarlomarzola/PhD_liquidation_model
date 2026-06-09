"""Risk metrics tracking and analysis."""

from dataclasses import dataclass, field
from typing import Dict, List
from environment.defi_env import DefiEnv, LendingPool


@dataclass
class PoolMetrics:
    """Metrics for a single lending pool."""

    blocks: List[int] = field(default_factory=list)
    available_liquidity: List[float] = field(default_factory=list)
    total_supply: List[float] = field(default_factory=list)
    total_borrow: List[float] = field(default_factory=list)
    usage_ratio: List[float] = field(default_factory=list)
    borrow_rate: List[float] = field(default_factory=list)
    supply_rate: List[float] = field(default_factory=list)
    bad_debt: List[float] = field(default_factory=list)
    treasury: List[float] = field(default_factory=list)
    supply_index: List[float] = field(default_factory=list)
    borrow_index: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for easy export."""
        return {
            'blocks': self.blocks,
            'available_liquidity': self.available_liquidity,
            'total_supply': self.total_supply,
            'total_borrow': self.total_borrow,
            'usage_ratio': self.usage_ratio,
            'borrow_rate': self.borrow_rate,
            'supply_rate': self.supply_rate,
            'bad_debt': self.bad_debt,
            'treasury': self.treasury,
            'supply_index': self.supply_index,
            'borrow_index': self.borrow_index,
        }


@dataclass
class SystemMetrics:
    """System-wide risk metrics."""

    blocks: List[int] = field(default_factory=list)
    total_bad_debt_usd: List[float] = field(default_factory=list)
    num_undercollateralized_users: List[int] = field(default_factory=list)
    max_health_factor_risk: List[float] = field(default_factory=list)
    liquidity_shortfall_events: List[Dict] = field(default_factory=list)
    liquidation_count: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'blocks': self.blocks,
            'total_bad_debt_usd': self.total_bad_debt_usd,
            'num_undercollateralized': self.num_undercollateralized_users,
            'max_hf_risk': self.max_health_factor_risk,
            'liquidity_shortfalls': self.liquidity_shortfall_events,
            'liquidation_count': self.liquidation_count,
        }


class MetricsCollector:
    """Collects metrics during simulation runs."""

    def __init__(self, env: DefiEnv):
        self.env = env
        self.pool_metrics: Dict[str, PoolMetrics] = {}
        self.system_metrics = SystemMetrics()
        self._initialize_pools()
        self._liquidation_count = 0

    def _initialize_pools(self) -> None:
        """Initialize metric tracking for all pools."""
        for pool_name, pool in self.env.lending_pools.items():
            self.pool_metrics[pool_name] = PoolMetrics()

    def record_step(self) -> None:
        """Record metrics at current block."""
        # Record pool metrics
        for pool_name, pool in self.env.lending_pools.items():
            metrics = self.pool_metrics[pool_name]

            total_supply = pool.total_scaled_supply * pool.supply_index
            total_borrow = pool.total_scaled_borrow * pool.borrow_index

            metrics.blocks.append(self.env.blocknumber)
            metrics.available_liquidity.append(pool.available_liquidity_cash)
            metrics.total_supply.append(total_supply)
            metrics.total_borrow.append(total_borrow)
            metrics.usage_ratio.append(pool.usage_ratio)
            metrics.borrow_rate.append(pool.borrow_rate)
            metrics.supply_rate.append(pool.supply_rate)
            metrics.bad_debt.append(pool.bad_debt)
            metrics.treasury.append(pool.treasury)
            metrics.supply_index.append(pool.supply_index)
            metrics.borrow_index.append(pool.borrow_index)

        # Record system metrics
        total_bad_debt = sum(pool.bad_debt * pool.underlying_token.price
                            for pool in self.env.lending_pools.values()
                            if pool.underlying_token.price)

        undercollateralized = [
            w for w in self.env.wallets.values()
            if w.health_factor < 1.0
        ]

        max_hf_risk = min((w.health_factor for w in self.env.wallets.values()),
                          default=float('inf'))

        self.system_metrics.blocks.append(self.env.blocknumber)
        self.system_metrics.total_bad_debt_usd.append(total_bad_debt)
        self.system_metrics.num_undercollateralized_users.append(len(undercollateralized))
        self.system_metrics.max_health_factor_risk.append(max_hf_risk)
        self.system_metrics.liquidation_count.append(self._liquidation_count)

    def record_liquidation(self) -> None:
        """Record that a liquidation occurred."""
        self._liquidation_count += 1

    def check_liquidity_shortfall(self) -> Dict[str, float]:
        """Check if any pool has insufficient liquidity."""
        shortfalls = {}
        for pool_name, pool in self.env.lending_pools.items():
            if pool.available_liquidity_cash < 0:
                shortfalls[pool_name] = abs(pool.available_liquidity_cash)
        return shortfalls

    def get_pool_metrics(self, pool_name: str) -> PoolMetrics:
        """Get metrics for a specific pool."""
        return self.pool_metrics.get(pool_name)

    def get_system_summary(self) -> dict:
        """Get summary statistics of system over simulation period."""
        if not self.system_metrics.blocks:
            return {}

        total_bad_debt = self.system_metrics.total_bad_debt_usd
        max_undercollateralized = max(self.system_metrics.num_undercollateralized_users,
                                       default=0)
        min_hf = min(self.system_metrics.max_health_factor_risk,
                     default=float('inf'))
        total_liquidations = self.system_metrics.liquidation_count[-1] if self.system_metrics.liquidation_count else 0

        return {
            'peak_bad_debt_usd': max(total_bad_debt) if total_bad_debt else 0,
            'final_bad_debt_usd': total_bad_debt[-1] if total_bad_debt else 0,
            'peak_undercollateralized': max_undercollateralized,
            'min_health_factor': min_hf,
            'total_liquidations': total_liquidations,
            'duration_blocks': self.system_metrics.blocks[-1] - self.system_metrics.blocks[0] if self.system_metrics.blocks else 0,
        }

    def to_dict(self) -> dict:
        """Export all metrics as nested dictionary."""
        return {
            'pools': {name: metrics.to_dict() for name, metrics in self.pool_metrics.items()},
            'system': self.system_metrics.to_dict(),
            'summary': self.get_system_summary(),
        }
