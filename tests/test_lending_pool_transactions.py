import pytest
from environment.defi_env import DefiEnv, Token, LendingPool, Wallet
from environment.parameters import pool_parameters


def test_borrow_health_factor_limit():
    env = DefiEnv(prices={"USDC": 1.0})

    # Create token and pool
    usdc = Token(env, "USDC")
    pool = LendingPool(env, usdc, **pool_parameters["usdc"])

    # Create wallet and fund it
    alice = Wallet(env, "alice")
    usdc.mint(alice, 1000)  # Alice has $1000

    # Supply to the pool
    pool.supply(alice, 1000)

    # Borrow a safe amount
    safe_borrow = alice.available_collateral_usd * 0.5
    pool.borrow(alice, safe_borrow)  # Should succeed

    # Borrow that would bring HF < 1
    with pytest.raises(AssertionError, match="Borrow would cause liquidation risk"):
        pool.borrow(alice, 1_000_000)  # Clearly above collateral


# TODO: Think about what tests need to be done w.r.t. supply, withdraw, borrow, repay

    # Supply with insufficient wallet funds
    # Supply beyond supply cap

    # Withdraw more than was supplied
    # Withdraw with insufficient pool liquidity
    # Withdraw such that HF<1

    # Borrow with insufficient collateral
    # Borrow with insufficient pool liquidity
    # Borrow beyond borrow cap
    # Borrow such that HF<1

    # Repay more than was borrowed
    # Repay with insufficient wallet funds
