from market_env.settings import PROJECT_ROOT

DATA_PATH = PROJECT_ROOT / "data"
FIGURE_PATH = PROJECT_ROOT / "figures"

# Aave market parameters
collateral_token          = 'WBTC'
debt_token                = 'USDC'
closing_factor            = 0.5
liquidation_bonus         = 0.045
liquidation_threshold     = 0.78

# Initial user LTV parameters
number_of_users   = 10_000
mu                = 0.5
sigma             = 0.15

# Simulation parameters
participation_proportion    = 0.1
collateral_price            = 100_000
debt_price                  = 1
total_collateral_usd        = 1e9
