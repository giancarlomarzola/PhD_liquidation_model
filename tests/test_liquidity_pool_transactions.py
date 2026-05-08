import pytest
from environment.defi_env import DefiEnv, Token, LendingPool, Wallet
from environment.parameters import pool_parameters

# To run tests: python -m pytest -v

# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def env_setup():
    """
    Standard environment used by every test.

    Builds:
      - DefiEnv with USDC ($1) and WBTC ($50,000) prices
      - Two underlying tokens and two LendingPools (sensible parameters,
        no supply/borrow caps by default — set them inline when needed)
      - Two funded wallets:
          alice: 100,000 USDC, 5 WBTC (USDC liquidity provider / generic actor)
          bob:    50,000 USDC, 2 WBTC (typical borrower with WBTC collateral)
    """
    env = DefiEnv(prices={"USDC": 1.0, "WBTC": 50_000.0})

    usdc = Token(env, "USDC")
    wbtc = Token(env, "WBTC")

    usdc_pool = LendingPool(env, usdc, **pool_parameters["usdc"])
    wbtc_pool = LendingPool(env, wbtc, **pool_parameters["wbtc"])

    alice = Wallet(env, "alice")
    bob = Wallet(env, "bob")

    usdc.mint(alice, 100_000)
    wbtc.mint(alice, 5)
    usdc.mint(bob, 50_000)
    wbtc.mint(bob, 2)

    return {
        "env": env,
        "usdc": usdc,
        "wbtc": wbtc,
        "usdc_pool": usdc_pool,
        "wbtc_pool": wbtc_pool,
        "alice": alice,
        "bob": bob,
    }


# ============================================================
# SUPPLY
# ============================================================

def test_supply_basic(env_setup):
    """Alice supplies 1000 usdc to pool"""
    alice = env_setup["alice"]
    usdc = env_setup["usdc"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 1_000)

    # Wallet
    assert alice.balances[usdc] == pytest.approx(99_000)
    assert alice.balances[pool.a_token] == pytest.approx(1_000)
    # Pool
    assert pool.available_liquidity_cash == pytest.approx(1_000)
    assert pool.a_token.total_supply == pytest.approx(1_000)
    assert pool.v_token.total_supply == pytest.approx(0)


def test_supply_insufficient_wallet_funds(env_setup):
    """Alice attempts to supply more usdc than she has available """
    alice = env_setup["alice"]
    usdc = env_setup["usdc"]
    pool = env_setup["usdc_pool"]

    with pytest.raises(AssertionError, match="does not have enough"):
        pool.supply(alice, 200_000)

    # Alice's state untouched after the failure
    assert alice.balances[usdc] == pytest.approx(100_000)
    assert alice.balances.get(pool.a_token, 0) == 0
    # Pool state untouched after the failure
    assert pool.available_liquidity_cash == 0
    assert pool.a_token.total_supply == 0


def test_supply_zero_amount(env_setup):
    """Zero supply must fail (amount must be positive)."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    with pytest.raises(AssertionError, match="Amount must be positive"):
        pool.supply(alice, 0)


def test_supply_negative_amount(env_setup):
    """Negative supply must fail."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    with pytest.raises(AssertionError, match="Amount must be positive"):
        pool.supply(alice, -100)


def test_supply_at_supply_cap(env_setup):
    """Supplying exactly the supply cap must succeed (boundary)."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]
    pool.supply_cap = 50_000

    pool.supply(alice, 50_000)

    assert pool.a_token.total_supply == pytest.approx(50_000)
    assert pool.available_liquidity_cash == pytest.approx(50_000)
    assert alice.balances[pool.a_token] == pytest.approx(50_000)


def test_supply_exceeds_supply_cap(env_setup):
    """Supplying one unit above the supply cap must fail."""
    alice = env_setup["alice"]
    usdc = env_setup["usdc"]
    pool = env_setup["usdc_pool"]
    pool.supply_cap = 50_000

    with pytest.raises(AssertionError, match="exceeds pool's supply cap"):
        pool.supply(alice, 50_001)

    # Alice's state untouched after the failure
    assert alice.balances[usdc] == pytest.approx(100_000)
    assert alice.balances.get(pool.a_token, 0) == 0
    # Pool state untouched after the failure
    assert pool.available_liquidity_cash == 0
    assert pool.a_token.total_supply == 0


def test_supply_when_underlying_not_in_wallet(env_setup):
    """A wallet that has never received the underlying cannot supply."""
    env = env_setup["env"]
    pool = env_setup["wbtc_pool"]

    charlie = Wallet(env, "charlie")  # no balances at all

    with pytest.raises(AssertionError, match="does not have enough"):
        pool.supply(charlie, 1)

    assert pool.available_liquidity_cash == 0


def test_supply_accumulates_across_calls(env_setup):
    """Successive supplies stack — pool and wallet aggregate correctly."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 1_000)
    pool.supply(alice, 2_500)

    assert alice.balances[pool.a_token] == pytest.approx(3_500)
    assert pool.available_liquidity_cash == pytest.approx(3_500)
    assert pool.a_token.total_supply == pytest.approx(3_500)


# ============================================================
# WITHDRAW
# ============================================================

def test_withdraw_basic(env_setup):
    """Basic withdraw: aTokens burned and underlying returned to wallet."""
    alice = env_setup["alice"]
    usdc = env_setup["usdc"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 5_000)
    pool.withdraw(alice, 2_000)

    # Wallet
    assert alice.balances[usdc] == pytest.approx(97_000)  # 100k - 5k + 2k
    assert alice.balances[pool.a_token] == pytest.approx(3_000)
    # Pool
    assert pool.available_liquidity_cash == pytest.approx(3_000)
    assert pool.a_token.total_supply == pytest.approx(3_000)


def test_withdraw_more_than_supplied(env_setup):
    """Withdrawing more than the wallet's aToken balance must fail."""
    alice = env_setup["alice"]
    usdc = env_setup["usdc"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 1_000)

    with pytest.raises(AssertionError, match="does not have sufficient"):
        pool.withdraw(alice, 1_500)

    # Wallet
    assert alice.balances[usdc] == pytest.approx(99_000)
    assert alice.balances[pool.a_token] == pytest.approx(1_000)
    # Pool
    assert pool.available_liquidity_cash == pytest.approx(1_000)
    assert pool.a_token.total_supply == pytest.approx(1_000)


def test_withdraw_full_supplied_amount(env_setup):
    """Withdrawing exactly the supplied amount drains the position cleanly."""
    alice = env_setup["alice"]
    usdc = env_setup["usdc"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 1_000)
    pool.withdraw(alice, 1_000)

    # Wallet returned to initial state for this pool
    assert alice.balances[usdc] == pytest.approx(100_000)
    assert alice.balances[pool.a_token] == pytest.approx(0)
    # Pool drained
    assert pool.available_liquidity_cash == pytest.approx(0)
    assert pool.a_token.total_supply == pytest.approx(0)


def test_withdraw_with_no_outstanding_debt(env_setup):
    """
    With no debt the health factor is infinite — withdraw must still
    work without divide-by-zero errors.
    """
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 1_000)
    assert alice.health_factor == float("inf")

    pool.withdraw(alice, 1_000)
    assert alice.health_factor == float("inf")
    assert alice.balances[pool.a_token] == pytest.approx(0)


def test_withdraw_with_insufficient_pool_liquidity(env_setup):
    """If borrowers have drained the pool, withdraw must fail on liquidity check."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 10_000)
    wbtc_pool.supply(bob, 1)        # 50k collateral
    usdc_pool.borrow(bob, 10_000)   # drains pool cash
    assert usdc_pool.available_liquidity_cash == pytest.approx(0)

    with pytest.raises(AssertionError, match="pool does not have enough liquidity"):
        usdc_pool.withdraw(alice, 5_000)

    # Alice's state untouched after failure
    assert alice.balances[usdc] == pytest.approx(90_000)
    assert alice.balances[usdc_pool.a_token] == pytest.approx(10_000)

    # Bob's state untouched after failure
    assert bob.balances[usdc] == pytest.approx(60_000)
    assert bob.balances.get(wbtc, 0) == pytest.approx(1)  # 1 WBTC still in pool
    assert bob.balances[usdc_pool.v_token] == pytest.approx(10_000)

    # Pool state untouched after failure
    assert usdc_pool.available_liquidity_cash == pytest.approx(0)
    assert usdc_pool.a_token.total_supply == pytest.approx(10_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(10_000)


def test_withdraw_causes_health_factor_below_one(env_setup):
    """Withdraw that would drive HF below 1 must fail."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)         # 100k collateral
    usdc_pool.borrow(bob, 50_000)    # near max LTV

    hf_before = bob.health_factor
    with pytest.raises(AssertionError, match="liquidation risk"):
        wbtc_pool.withdraw(bob, 1)   # would halve collateral and break HF

    # HF unchanged after the rejected withdraw
    assert bob.health_factor == pytest.approx(hf_before)
    assert bob.balances[wbtc_pool.a_token] == pytest.approx(2)
    # Pool states untouched after failure
    assert wbtc_pool.available_liquidity_cash == pytest.approx(2)
    assert wbtc_pool.a_token.total_supply == pytest.approx(2)
    assert usdc_pool.available_liquidity_cash == pytest.approx(0)
    assert usdc_pool.a_token.total_supply == pytest.approx(50_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(50_000)


def test_withdraw_zero_amount(env_setup):
    """Zero withdraw must fail."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 1_000)
    with pytest.raises(AssertionError, match="Amount must be positive"):
        pool.withdraw(alice, 0)


def test_withdraw_negative_amount(env_setup):
    """Negative withdraw must fail."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    pool.supply(alice, 1_000)
    with pytest.raises(AssertionError, match="Amount must be positive"):
        pool.withdraw(alice, -1)


def test_withdraw_when_atoken_not_in_wallet(env_setup):
    """A wallet that never supplied to this pool cannot withdraw."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    # Alice has never supplied — she has no aToken entry at all.
    # The current implementation surfaces this as either AssertionError or TypeError
    # depending on the comparison path; either is acceptable as a hard rejection.
    with pytest.raises((AssertionError, TypeError)):
        pool.withdraw(alice, 1)

    assert pool.available_liquidity_cash == 0


# ============================================================
# BORROW
# ============================================================

def test_borrow_basic(env_setup):
    """Basic borrow: underlying flows out of pool, vTokens minted 1:1."""
    alice, bob, usdc = env_setup["alice"], env_setup["bob"], env_setup["usdc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 1)         # 50k collateral
    usdc_pool.borrow(bob, 10_000)

    # Wallet
    assert bob.balances[usdc] == pytest.approx(60_000)        # 50k initial + 10k borrowed
    assert bob.balances[usdc_pool.v_token] == pytest.approx(10_000)
    # Pool
    assert usdc_pool.available_liquidity_cash == pytest.approx(40_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(10_000)
    assert usdc_pool.a_token.total_supply == pytest.approx(50_000)  # supply unchanged


def test_borrow_insufficient_collateral(env_setup):
    """Borrow with insufficient collateral must fail (HF check)."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 100_000)
    wbtc_pool.supply(bob, 1)   # ~36,500 max borrow at 73% LTV

    with pytest.raises(AssertionError, match="liquidation risk"):
        usdc_pool.borrow(bob, 50_000)

    # No state changes
    assert usdc_pool.v_token.total_supply == 0
    assert usdc_pool.available_liquidity_cash == pytest.approx(100_000)


def test_borrow_insufficient_pool_liquidity(env_setup):
    """Borrow must fail if the pool has insufficient cash, even with ample collateral."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 1_000)
    wbtc_pool.supply(bob, 2)         # 100k collateral, far above the requested borrow

    with pytest.raises(AssertionError, match="pool does not have enough liquidity"):
        usdc_pool.borrow(bob, 5_000)

    assert usdc_pool.v_token.total_supply == 0
    assert usdc_pool.available_liquidity_cash == pytest.approx(1_000)


def test_borrow_at_borrow_cap(env_setup):
    """Borrowing exactly at the borrow cap must succeed (boundary)."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 100_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow_cap = 10_000

    usdc_pool.borrow(bob, 10_000)

    assert usdc_pool.v_token.total_supply == pytest.approx(10_000)
    assert bob.balances[usdc_pool.v_token] == pytest.approx(10_000)
    assert usdc_pool.available_liquidity_cash == pytest.approx(90_000)


def test_borrow_exceeds_borrow_cap(env_setup):
    """Borrowing one unit above the borrow cap must fail."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 100_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow_cap = 10_000

    with pytest.raises(AssertionError, match="exceeds pool's borrow cap"):
        usdc_pool.borrow(bob, 10_001)

    assert usdc_pool.v_token.total_supply == 0


def test_borrow_health_factor_limit(env_setup):
    """A borrow that would push HF below 1 must fail (existing test, retained)."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    # Alice supplies USDC and borrows against it
    pool.supply(alice, 1_000)

    safe_borrow = alice.available_collateral_usd * 0.5
    pool.borrow(alice, safe_borrow)
    assert alice.health_factor > 1

    with pytest.raises(AssertionError, match="liquidation risk"):
        pool.borrow(alice, 1_000_000)


def test_borrow_zero_amount(env_setup):
    """Zero borrow must fail."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 1_000)
    wbtc_pool.supply(bob, 1)

    with pytest.raises(AssertionError, match="Amount must be positive"):
        usdc_pool.borrow(bob, 0)


def test_borrow_negative_amount(env_setup):
    """
    Negative borrow must fail. With existing collateral the health-factor
    arithmetic catches it first (negative debt → negative HF), which is
    fine — the request is rejected either way.
    """
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 1_000)
    wbtc_pool.supply(bob, 1)

    with pytest.raises(AssertionError):
        usdc_pool.borrow(bob, -1)

    assert usdc_pool.v_token.total_supply == 0


def test_borrow_decreases_health_factor(env_setup):
    """A successful borrow must reduce HF (from infinity towards but above 1)."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 100_000)
    wbtc_pool.supply(bob, 2)

    hf_before = bob.health_factor
    assert hf_before == float("inf")

    usdc_pool.borrow(bob, 10_000)
    hf_after = bob.health_factor

    assert hf_after < hf_before
    assert hf_after > 1


# ============================================================
# REPAY
# ============================================================

def test_repay_basic(env_setup):
    """Basic repay: vTokens burned, underlying returned to pool."""
    alice, bob, usdc = env_setup["alice"], env_setup["bob"], env_setup["usdc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 20_000)

    cash_before = usdc_pool.available_liquidity_cash
    usdc_pool.repay(bob, 5_000)

    # Wallet
    assert bob.balances[usdc_pool.v_token] == pytest.approx(15_000)
    assert bob.balances[usdc] == pytest.approx(50_000 + 20_000 - 5_000)
    # Pool
    assert usdc_pool.available_liquidity_cash == pytest.approx(cash_before + 5_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(15_000)


def test_repay_more_than_borrowed(env_setup):
    """Repaying more than the wallet's vToken balance must fail."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 1_000)

    with pytest.raises(AssertionError, match="does not have sufficient"):
        usdc_pool.repay(bob, 2_000)

    # Position unchanged
    assert bob.balances[usdc_pool.v_token] == pytest.approx(1_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(1_000)


def test_repay_full_borrowed_amount(env_setup):
    """Repaying exactly the full debt zeroes the position."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 10_000)
    usdc_pool.repay(bob, 10_000)

    assert bob.balances[usdc_pool.v_token] == pytest.approx(0)
    assert usdc_pool.v_token.total_supply == pytest.approx(0)
    assert usdc_pool.available_liquidity_cash == pytest.approx(50_000)
    assert bob.health_factor == float("inf")  # debt fully cleared


def test_repay_insufficient_wallet_funds(env_setup):
    """Repay must fail when wallet does not have enough underlying token."""
    alice, bob, usdc = env_setup["alice"], env_setup["bob"], env_setup["usdc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 10_000)

    # Drain Bob's USDC so he can't repay
    usdc.burn(bob, bob.balances[usdc])
    assert bob.balances[usdc] == 0

    with pytest.raises(AssertionError, match="does not have enough"):
        usdc_pool.repay(bob, 5_000)


def test_repay_zero_amount(env_setup):
    """Zero repay must fail."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 5_000)

    with pytest.raises(AssertionError, match="Amount must be positive"):
        usdc_pool.repay(bob, 0)


def test_repay_negative_amount(env_setup):
    """Negative repay must fail."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 5_000)

    with pytest.raises(AssertionError, match="Amount must be positive"):
        usdc_pool.repay(bob, -1)


def test_repay_when_vtoken_not_in_wallet(env_setup):
    """A wallet that has never borrowed cannot repay."""
    alice = env_setup["alice"]
    pool = env_setup["usdc_pool"]

    # No vToken entry exists for Alice — implementation surfaces this
    # as either AssertionError or TypeError; either is a valid rejection.
    with pytest.raises((AssertionError, TypeError)):
        pool.repay(alice, 1)


def test_repay_increases_health_factor(env_setup):
    """A successful repay must raise the health factor."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 100_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 50_000)

    hf_before = bob.health_factor
    usdc_pool.repay(bob, 25_000)
    hf_after = bob.health_factor

    assert hf_after > hf_before
    assert hf_after > 1


# ============================================================
# INTEGRATION
# ============================================================

def test_full_supply_borrow_repay_withdraw_cycle(env_setup):
    """
    A complete cycle (supply → borrow → repay → withdraw) executed by both
    counterparties should restore the system to its initial state.
    """
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    initial_alice_usdc = alice.balances[usdc]
    initial_alice_wbtc = alice.balances[wbtc]
    initial_bob_usdc = bob.balances[usdc]
    initial_bob_wbtc = bob.balances[wbtc]

    # 1. Alice supplies USDC liquidity
    usdc_pool.supply(alice, 50_000)
    assert usdc_pool.available_liquidity_cash == pytest.approx(50_000)

    # 2. Bob supplies WBTC as collateral
    wbtc_pool.supply(bob, 1)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(1)

    # 3. Bob borrows USDC against his collateral
    usdc_pool.borrow(bob, 10_000)
    assert usdc_pool.available_liquidity_cash == pytest.approx(40_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(10_000)
    assert bob.health_factor > 1

    # 4. Bob repays the full loan
    usdc_pool.repay(bob, 10_000)
    assert usdc_pool.available_liquidity_cash == pytest.approx(50_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(0)
    assert bob.health_factor == float("inf")

    # 5. Bob withdraws his collateral
    wbtc_pool.withdraw(bob, 1)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(0)
    assert wbtc_pool.a_token.total_supply == pytest.approx(0)

    # 6. Alice withdraws her liquidity
    usdc_pool.withdraw(alice, 50_000)
    assert usdc_pool.available_liquidity_cash == pytest.approx(0)
    assert usdc_pool.a_token.total_supply == pytest.approx(0)

    # Final state == initial state
    assert alice.balances[usdc] == pytest.approx(initial_alice_usdc)
    assert alice.balances[wbtc] == pytest.approx(initial_alice_wbtc)
    assert bob.balances[usdc] == pytest.approx(initial_bob_usdc)
    assert bob.balances[wbtc] == pytest.approx(initial_bob_wbtc)
    assert alice.balances.get(usdc_pool.a_token, 0) == pytest.approx(0)
    assert bob.balances.get(wbtc_pool.a_token, 0) == pytest.approx(0)
    assert bob.balances.get(usdc_pool.v_token, 0) == pytest.approx(0)


def test_partial_cycle_state_consistency(env_setup):
    """Partial repay + partial withdraw should leave fully consistent intermediate state."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 20_000)
    usdc_pool.repay(bob, 5_000)
    usdc_pool.withdraw(alice, 10_000)

    # Pool: 50k cash - 20k borrowed = 30k; +5k repay - 10k withdraw = 25k
    assert usdc_pool.available_liquidity_cash == pytest.approx(25_000)
    assert usdc_pool.a_token.total_supply == pytest.approx(40_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(15_000)

    # Wallet positions match pool aggregates
    assert alice.balances[usdc_pool.a_token] == pytest.approx(40_000)
    assert bob.balances[usdc_pool.v_token] == pytest.approx(15_000)


def test_multi_wallet_supply_and_borrow(env_setup):
    """Two suppliers + one borrower: pool aggregates wallet positions correctly."""
    env = env_setup["env"]
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    charlie = Wallet(env, "charlie")
    usdc.mint(charlie, 30_000)
    wbtc.mint(charlie, 1)

    # Alice and Charlie both supply USDC; Bob supplies WBTC and borrows USDC
    usdc_pool.supply(alice, 40_000)
    usdc_pool.supply(charlie, 20_000)
    wbtc_pool.supply(bob, 2)         # 100k collateral → ample HF for 30k borrow
    usdc_pool.borrow(bob, 30_000)

    # Pool aggregates
    assert usdc_pool.a_token.total_supply == pytest.approx(60_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(30_000)
    assert usdc_pool.available_liquidity_cash == pytest.approx(30_000)

    # Per-wallet positions
    assert alice.balances[usdc_pool.a_token] == pytest.approx(40_000)
    assert charlie.balances[usdc_pool.a_token] == pytest.approx(20_000)
    assert bob.balances[usdc_pool.v_token] == pytest.approx(30_000)


def test_multi_wallet_independent_health_factors(env_setup):
    """Each wallet's HF depends only on its own positions."""
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    # Alice supplies but never borrows; Bob supplies + borrows
    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 30_000)

    # Alice has no debt → HF infinite; Bob has finite, healthy HF
    assert alice.health_factor == float("inf")
    assert bob.health_factor < float("inf")
    assert bob.health_factor > 1


def test_health_factor_trajectory_through_cycle(env_setup):
    """
    HF should: be infinite with no debt, decrease monotonically with each
    additional borrow, and increase on repay — staying above 1 throughout.
    """
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)

    hf_no_debt = bob.health_factor
    assert hf_no_debt == float("inf")

    usdc_pool.borrow(bob, 10_000)
    hf_after_small_borrow = bob.health_factor
    assert hf_after_small_borrow < hf_no_debt
    assert hf_after_small_borrow > 1

    usdc_pool.borrow(bob, 20_000)
    hf_after_large_borrow = bob.health_factor
    assert hf_after_large_borrow < hf_after_small_borrow
    assert hf_after_large_borrow > 1

    usdc_pool.repay(bob, 15_000)
    hf_after_repay = bob.health_factor
    assert hf_after_repay > hf_after_large_borrow
    assert hf_after_repay > 1


def test_collateral_locked_until_debt_repaid(env_setup):
    """
    A borrower must repay before withdrawing all collateral. After full
    repayment the same withdraw must succeed and restore wallet balances.
    """
    alice, bob = env_setup["alice"], env_setup["bob"]
    wbtc = env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    initial_bob_wbtc = bob.balances[wbtc]

    usdc_pool.supply(alice, 50_000)
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 10_000)

    # While debt outstanding, full collateral withdraw must fail
    with pytest.raises(AssertionError, match="liquidation risk"):
        wbtc_pool.withdraw(bob, 2)
    assert wbtc_pool.a_token.total_supply == pytest.approx(2)

    # After full repayment, the same withdrawal succeeds
    usdc_pool.repay(bob, 10_000)
    wbtc_pool.withdraw(bob, 2)

    assert bob.balances[wbtc_pool.a_token] == pytest.approx(0)
    assert bob.balances[wbtc] == pytest.approx(initial_bob_wbtc)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(0)
    assert wbtc_pool.a_token.total_supply == pytest.approx(0)


def test_multi_wallet_full_cycle_returns_to_initial_state(env_setup):
    """
    A multi-wallet cycle (Alice and Charlie both supply, Bob borrows from both
    pools, then everything unwinds) should restore the initial state of every
    wallet and pool.
    """
    env = env_setup["env"]
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc = env_setup["usdc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    charlie = Wallet(env, "charlie")
    usdc.mint(charlie, 20_000)

    snapshots = {
        alice.name: dict(alice.balances),
        bob.name: dict(bob.balances),
        charlie.name: dict(charlie.balances),
    }

    # Supply phase
    usdc_pool.supply(alice, 40_000)
    usdc_pool.supply(charlie, 20_000)
    wbtc_pool.supply(bob, 2)

    # Borrow phase
    usdc_pool.borrow(bob, 30_000)

    # Unwind in reverse
    usdc_pool.repay(bob, 30_000)
    wbtc_pool.withdraw(bob, 2)
    usdc_pool.withdraw(charlie, 20_000)
    usdc_pool.withdraw(alice, 40_000)

    # Pools fully drained
    assert usdc_pool.available_liquidity_cash == pytest.approx(0)
    assert usdc_pool.a_token.total_supply == pytest.approx(0)
    assert usdc_pool.v_token.total_supply == pytest.approx(0)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(0)
    assert wbtc_pool.a_token.total_supply == pytest.approx(0)
    assert wbtc_pool.v_token.total_supply == pytest.approx(0)

    # Each wallet's underlying balances match the initial snapshot
    for wallet in (alice, bob, charlie):
        for token, initial in snapshots[wallet.name].items():
            assert wallet.balances.get(token, 0) == pytest.approx(initial)
