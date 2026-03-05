# Pool parameters:

# Better as individual dicts, or nested dict so i have one main pool_parameters dict with each value being the dict for the key's token?

pool_parameters = {
    "usdc": {
        "max_ltv": 0.75,
        "liquidation_threshold": 0.78,
        "liquidation_bonus": 0.045,
        "closing_factor": 0.5,
        "interest_slope_1": 0.065,
        "interest_slope_2": 0.1,
        "interest_base_rate": 0.0,
        "optimal_usage_ratio": 0.92,
        "reserve_rate": 0.2,
    },
    "wbtc": {
        "max_ltv": 0.73,
        "liquidation_threshold": 0.78,
        "liquidation_bonus": 0.05,
        "closing_factor": 0.5,
        "interest_slope_1": 0.04,
        "interest_slope_2": 3.0,
        "interest_base_rate": 0.0,
        "optimal_usage_ratio": 0.8,
        "reserve_rate": 0.2,
    },
}
