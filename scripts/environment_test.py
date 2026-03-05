from environment.defi_env import DefiEnv, Token, aToken, vToken, Wallet, LendingPool
from environment.parameters import pool_parameters

# ========================================================================================================================
# Basic test example
# Market with 2 tokens (USDC, WBTC)
# ========================================================================================================================


def print_current_state():
    print(Alice)
    print(Bob)
    print(usdc_pool)
    print(wbtc_pool)


defi_env = DefiEnv(prices={"usdc": 1.0001, "wbtc": 50000})

usdc = Token(defi_env, "usdc")
wbtc = Token(defi_env, "wbtc")

usdc_pool = LendingPool(
    env=defi_env,
    underlying_token=usdc,
    **pool_parameters["usdc"],  # is it ok to do this?
)
wbtc_pool = LendingPool(env=defi_env, underlying_token=wbtc, **pool_parameters["wbtc"])

# Create users
Alice = Wallet(defi_env, "alice")
Bob = Wallet(defi_env, "bob")

# Provide initial wallet funds (ca 100k USD for both)
usdc.mint(Alice, 100_000)
wbtc.mint(Bob, 2)

print(f"{'='*50}\n" "Initial state\n" f"{'='*50}\n")
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)


print(f"{'='*50}\n" "Supplies to each pool (100k USD for both)\n" f"{'='*50}\n")
usdc_pool.supply(Alice, 100_000)
wbtc_pool.supply(Bob, 2)
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)


print(f"{'='*50}\n" "Borrows from each pool(25k USD for both)\n" f"{'='*50}\n")
usdc_pool.borrow(Bob, 25_000)
wbtc_pool.borrow(Alice, 0.5)
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)

"""
print(
    f"{'='*50}\n"
    "Repay the full borrowed amount from each pool\n"
    f"{'='*50}\n"
    )
usdc_pool.repay(Bob, Bob.balances.get(usdc_pool.v_token))
wbtc_pool.repay(Alice, Alice.balances.get(wbtc_pool.v_token))
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)


print(
    f"{'='*50}\n"
    "Withdraw full amount of supplies from each pool\n"
    f"{'='*50}\n"
    )
usdc_pool.withdraw(Alice, Alice.balances.get(usdc_pool.a_token))
wbtc_pool.withdraw(Bob, Bob.balances.get(wbtc_pool.a_token))
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)
"""
