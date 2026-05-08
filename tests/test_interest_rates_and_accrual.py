# Placeholder
# Write tests to ensure interest accrual works as intended


# Borrow rate
    # Borrow rate at exactly 0% utilisation equals base rate
    # Borrow rate at exactly optimal utilisation equals base rate + slope_1
    # Borrow rate above optimal utilisation uses slope_2 (kink point behaviour)
    # Borrow rate at 100% utilisation (maximum stress)

# Reserve factor
    # A portion of borrow interest equal to reserve_rate flows to treasury, not suppliers
    # Supply rate is less than borrow rate (due to reserve factor)
    # Treasury balance increases correctly on repayment
    # With reserve_rate = 0, supply rate equals borrow rate (adjusted for utilisation)
    # With reserve_rate = 1, supply rate = 0

# Supply rate
    # Supply rate with 0 borrows
    # Supply rate is always <= borrow rate (depending on reserve factor)

# Accrual mechanics
    # Interest accrues correctly over multiple blocks (not just 1)
    # Interest accrues proportionally — 2 blocks should accrue ~2x one block
    # Interest accrues as part of transactions, and before transaction is executed
    # Two borrows of the same size accrue the same interest over the same period
    # A larger borrow accrues proportionally more interest than a smaller one
    # Interest accrues to both sides correctly — supplier rate derived from borrow rate and reserve factor

# Edge cases
    # Interest accrual at 0% utilisation leaves balances unchanged
    # Interest does not accrue retrospectively if a transaction is missed
    # Borrow rate never goes negative regardless of parameters
    # Very small borrow over many blocks (rounding/precision check)
    # Interest accrual with supply cap already reached

# Integration
    # After borrow + interest accrual, repaying only the original principal leaves residual v_token debt equal to accrued interest
    # Full repayment including interest restores pool to correct state
    # Supplier withdrawing after interest accrual receives more than they deposited