from market_env.constants import *
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

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
    'borrowed_tokens':  user_debts/debt_price,
    'supplied_tokens':  user_collaterals/collateral_price,
    'borrowed_usd':     user_debts,
    'supplied_usd':     user_collaterals,
    'ltv':              user_ltvs
})


# Plot initial user LTV distribution
fig, ax = plt.subplots(figsize=(8,4))
ax.hist(initial_user_positions['ltv'], bins=50, alpha=0.5, density=True)
ax.axvline(mu, color='red', linestyle='--', label=f'Mean LTV ({mu*100:.2f}%)')
ax.axvline(liquidation_threshold, color='grey', linestyle='--', label=f'Liquidation Threshold ({liquidation_threshold*100:.2f}%)')
ax.set_xlabel('User LTV')
ax.set_ylabel('Density')
ax.set_title('Distribution of User LTVs')
ax.legend()

# --- Compute stats ---
users_above_threshold = initial_user_positions[initial_user_positions['ltv'] >= liquidation_threshold]
num_users = users_above_threshold['ltv'].count()
total_supply = users_above_threshold["supplied_usd"].sum()
total_debt = users_above_threshold["borrowed_usd"].sum()

# --- Add text below plot (figure coordinates) ---
fig.text(
    0.1, -0.15,  # x, y in figure coordinates (y<0 moves it below the axes)
f"Total number of simulated users: {number_of_users:,}\n\
Number of users above liquidation threshold: {num_users}\n\
Total supply of users above threshold (USD): {total_supply:,.2f}\n\
Total debt of users above threshold (USD): {total_debt:,.2f}",
    fontsize=9
)

# --- Save figure ---

#plt.savefig(FIGURE_PATH/"user_ltv_distribution.pdf", bbox_inches='tight', pad_inches=0.2)
plt.show()