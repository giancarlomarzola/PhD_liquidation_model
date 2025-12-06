from market_env.constants import (
    coll_token, debt_token, initial_coll_price, initial_debt_price,
    closing_factor, liquidation_bonus, liquidation_threshold, 
    time_steps, number_of_users, mu, sigma, participation_proportion, total_collateral_usd
)
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import random
from __future__ import annotations

# Simulate price series for both collateral and debt token
# TODO: Replace with more advanced price simulation model
def simulate_prices(time_steps: int, initial_price: float, percent_price_change: float) -> list[float]:
    simulated_prices = [initial_price]
    percent_price_change = percent_price_change/100
    for _ in range(1, time_steps):
        # randomly decide whether to add or subtract the price change
        sign = +1 if random.random() < 0.5 else -1
        new_price = simulated_prices[-1] * (1 + sign * percent_price_change)
        simulated_prices.append(new_price)
    return simulated_prices

coll_prices = simulate_prices(time_steps, initial_coll_price, percent_price_change=1)
debt_prices = simulate_prices(time_steps, initial_debt_price, percent_price_change=0.01)



# Create market class
class Market:
    def __init__(
        self, 
        time_steps: int,
        coll_token: str,
        debt_token: str,
        coll_prices: list[float],
        debt_prices: list[float],
        closing_factor: float, 
        liquidation_bonus: float,
        liquidation_threshold: float, 
        users: dict[str, User] | None = None
    ):
        # Initialize users if not provided
        self.users = users or {}

        self.time_steps = time_steps
        self.closing_factor = closing_factor
        self.liquidation_bonus = liquidation_bonus
        self.liquidation_threshold = liquidation_threshold

        # Check that price series lengths match time_steps
        if len(coll_prices) != time_steps:
            raise ValueError("coll_prices length must equal time_steps")
        if len(debt_prices) != time_steps:
            raise ValueError("debt_prices length must equal time_steps")

        # Store price series
        self.price_series = {
            coll_token: coll_prices,
            debt_token: debt_prices,
        }

# Create user as class 
class User:
    def __init__(
        self, 
        user_id: int, 
        coll_usd: float, 
        debt_usd: float, 
        coll_price: float, 
        debt_price: float
    ):
        self.id = user_id
        
        # Positions in tokens
        self.supplied_tokens = coll_usd / coll_price
        self.borrowed_tokens = debt_usd / debt_price

        # Positions in USD
        self.supplied_usd = coll_usd
        self.borrowed_usd = debt_usd

        # Current LTV
        self.ltv = debt_usd / coll_usd if coll_usd > 0 else 0.0

        # Optional: history for simulation
        self.supplied_history = [self.supplied_usd]
        self.borrowed_history = [self.borrowed_usd]
        self.ltv_history = [self.ltv]

    def update_position(self, delta_coll_usd: float, delta_debt_usd: float):
        """Update positions and log history"""
        self.supplied_usd += delta_coll_usd
        self.borrowed_usd += delta_debt_usd

        # Update token amounts
        self.supplied_tokens += delta_coll_usd / (self.supplied_usd / self.supplied_tokens if self.supplied_tokens else 1)
        self.borrowed_tokens += delta_debt_usd / (self.borrowed_usd / self.borrowed_tokens if self.borrowed_tokens else 1)

        # Update LTV
        self.ltv = self.borrowed_usd / self.supplied_usd if self.supplied_usd > 0 else 0.0

        # Log history
        self.supplied_history.append(self.supplied_usd)
        self.borrowed_history.append(self.borrowed_usd)
        self.ltv_history.append(self.ltv)


# --- Generate initial users ---

# LTV distribution
user_ltvs = np.random.lognormal(np.log(mu), sigma, number_of_users)
user_ltvs = np.clip(user_ltvs, 0, liquidation_threshold)

# Allocate collateral proportionally
weights = user_ltvs / user_ltvs.sum()
user_collaterals = weights * total_collateral_usd
user_debts = user_collaterals * user_ltvs

# Create User instances
users = {
    i: User(
        user_id=i,
        collateral_usd=user_collaterals[i],
        debt_usd=user_debts[i],
        collateral_price=initial_coll_price,
        debt_price=initial_debt_price
    )
    for i in range(number_of_users)
}

# Generate initial LTV distribution of users
user_ltvs = np.random.lognormal(np.log(mu), sigma, number_of_users) # Array of n LTVs following the given distribution

# Clip values so there are no negative LTVs and there is no need for liquidation before loop
user_ltvs = np.clip(user_ltvs, 0, liquidation_threshold) 

# Create user positions from the LTVs
weights = user_ltvs / user_ltvs.sum()

# Allocate collateral 
user_collaterals = weights * total_collateral_usd

# Allocate respective debt
user_debts = user_collaterals * user_ltvs

# Construct user df
# Initialise user_positions df for the first block

# Distribute total supplies and debts, given LTVs
initial_user_positions = pd.DataFrame({
    'id':               range(0,number_of_users),
    'borrowed_tokens':  user_debts/initial_debt_price,
    'supplied_tokens':  user_collaterals/initial_coll_price,
    'borrowed_usd':     user_debts,
    'supplied_usd':     user_collaterals,
    'ltv':              user_ltvs
})

