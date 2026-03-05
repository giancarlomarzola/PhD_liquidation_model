# test_wallet_borrow.py
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
