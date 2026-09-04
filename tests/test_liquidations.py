import pytest
from environment.defi_env import DefiEnv, Token, LendingPool, Wallet
from environment.parameters import pool_parameters

# ============================================================
# Fixtures / helpers
# ============================================================

@pytest.fixture
def env_setup():
    """
    Environment for liquidation tests.

    Builds:
        - DefiEnv with USDC ($1) and WBTC ($50,000)
        - USDC and WBTC lending pools (standard parameters, no caps)
        - Wallets:
            alice:      200,000 USDC        (USDC liquidity provider)
            bob:        2 WBTC              (borrower, WBTC collateral)
            liquidator: 200,000 USDC        
    """
    env = DefiEnv(prices={"USDC": 1.0, "WBTC": 50_000.0})

    usdc = Token(env, "USDC")
    wbtc = Token(env, "WBTC")

    usdc_pool = LendingPool(env, usdc, **pool_parameters["usdc"])
    wbtc_pool = LendingPool(env, wbtc, **pool_parameters["wbtc"])

    alice = Wallet(env, "alice")
    bob = Wallet(env, "bob")
    liquidator = Wallet(env, "liquidator")

    usdc.mint(alice, 200_000)
    wbtc.mint(bob, 2)
    usdc.mint(liquidator, 200_000)

    return {
        "env": env,
        "usdc": usdc,
        "wbtc": wbtc,
        "usdc_pool": usdc_pool,
        "wbtc_pool": wbtc_pool,
        "alice": alice,
        "bob": bob,
        "liquidator": liquidator,
    }


def open_bob_position(env_setup, borrow_usdc=70_000, alice_supply=100_000, bob_wbtc=2):
    """
    Standard starting position:
        - alice supplies USDC liquidity
        - bob supplies WBTC collateral and borrows USDC (HF > 1 at current price)
    """
    alice, bob = env_setup["alice"], env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    usdc_pool.supply(alice, alice_supply)
    wbtc_pool.supply(bob, bob_wbtc)
    usdc_pool.borrow(bob, borrow_usdc)
    assert bob.health_factor > 1


def liquidate_until_clear(
    liquidator, debt_pool, borrower, collateral_pool, debt_underlying, max_rounds=50
):
    """
    Repeatedly liquidate `borrower` (closing-factor capped each call) until the
    debt is cleared -- either fully repaid or written off as bad debt.

    Returns (rounds_executed, total_debt_underlying_repaid_by_liquidator).
    """
    start_balance = liquidator.balances.get(debt_underlying, 0.0)
    rounds = 0
    while rounds < max_rounds:
        debt = debt_pool.get_actual_borrow_balance(borrower)
        if debt <= 1e-6:
            break
        available = liquidator.balances.get(debt_underlying, 0.0)
        repay = min(debt * debt_pool.closing_factor, available)
        if repay <= 1e-9:
            break
        liquidator.liquidate(debt_pool, borrower, repay, collateral_pool=collateral_pool)
        rounds += 1
    total_repaid = start_balance - liquidator.balances.get(debt_underlying, 0.0)
    return rounds, total_repaid


# ============================================================
# GUARD CONDITIONS
# ============================================================

def test_liquidate_healthy_borrower_rejected(env_setup):
    """A borrower with HF >= 1 cannot be liquidated."""
    bob = env_setup["bob"]
    liquidator = env_setup["liquidator"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    open_bob_position(env_setup, borrow_usdc=50_000)  # HF ~ 1.56
    assert bob.health_factor > 1

    with pytest.raises(AssertionError, match="not undercollateralized"):
        liquidator.liquidate(usdc_pool, bob, 10_000, collateral_pool=wbtc_pool)

    # Nothing moved
    assert bob.balances[usdc_pool.v_token] == pytest.approx(50_000)
    assert bob.balances[wbtc_pool.a_token] == pytest.approx(2)
    assert liquidator.balances[env_setup["usdc"]] == pytest.approx(200_000)
    assert usdc_pool.bad_debt == pytest.approx(0)


def test_liquidate_repay_above_closing_factor_rejected(env_setup):
    """Repaying more than closing_factor * debt in a single call must fail."""
    env = env_setup["env"]
    bob = env_setup["bob"]
    liquidator = env_setup["liquidator"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 42_000.0
    assert bob.health_factor < 1

    # closing factor is 0.5 -> max repay is 35,000
    with pytest.raises(AssertionError, match="exceeds closing factor maximum"):
        liquidator.liquidate(usdc_pool, bob, 40_000, collateral_pool=wbtc_pool)

    assert bob.balances[usdc_pool.v_token] == pytest.approx(70_000)
    assert usdc_pool.bad_debt == pytest.approx(0)


def test_liquidate_insufficient_liquidator_funds_rejected(env_setup):
    """A liquidator without enough underlying to fund the repay must fail."""
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 42_000.0

    poor = Wallet(env, "poor")
    usdc.mint(poor, 1_000)

    with pytest.raises(AssertionError, match="has insufficient"):
        poor.liquidate(usdc_pool, bob, 35_000, collateral_pool=wbtc_pool)

    assert poor.balances[usdc] == pytest.approx(1_000)
    assert poor.balances.get(wbtc, 0) == pytest.approx(0)
    assert bob.balances[usdc_pool.v_token] == pytest.approx(70_000)
    assert usdc_pool.bad_debt == pytest.approx(0)


def test_liquidate_insufficient_collateral_pool_cash_rejected(env_setup):
    """
    If the collateral pool's cash has been borrowed out, the seized collateral
    cannot be paid to the liquidator and the call must fail without side effects.
    """
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)

    # dave supplies USDC collateral and borrows almost all the WBTC cash
    dave = Wallet(env, "dave")
    usdc.mint(dave, 300_000)
    usdc_pool.supply(dave, 300_000)
    wbtc_pool.borrow(dave, 1.9)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(0.1)

    env.prices["WBTC"] = 42_000.0
    assert bob.health_factor < 1

    with pytest.raises(AssertionError, match="insufficient cash"):
        liquidator.liquidate(usdc_pool, bob, 35_000, collateral_pool=wbtc_pool)

    # bob untouched, liquidator untouched
    assert bob.balances[usdc_pool.v_token] == pytest.approx(70_000)
    assert bob.balances[wbtc_pool.a_token] == pytest.approx(2)
    assert liquidator.balances[usdc] == pytest.approx(200_000)
    assert liquidator.balances.get(wbtc, 0) == pytest.approx(0)
    assert usdc_pool.bad_debt == pytest.approx(0)


# ============================================================
# SUCCESSFUL LIQUIDATION (no bad debt)
# ============================================================

def test_partial_liquidation_no_bad_debt(env_setup):
    """
    Mildly underwater borrower (collateral still exceeds debt): one closing-factor
    liquidation repays 50% of the debt, seizes collateral + bonus, creates no bad
    debt, and lifts HF back above 1.
    """
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 42_000.0  # collateral 84k > debt 70k
    assert bob.health_factor == pytest.approx(84_000 * 0.78 / 70_000)
    assert bob.health_factor < 1

    liquidator.liquidate(usdc_pool, bob, 35_000, collateral_pool=wbtc_pool)

    # Debt halved
    assert bob.balances[usdc_pool.v_token] == pytest.approx(35_000)
    assert usdc_pool.v_token.total_supply == pytest.approx(35_000)
    assert usdc_pool.total_scaled_borrow == pytest.approx(35_000)
    assert usdc_pool.available_liquidity_cash == pytest.approx(65_000)  # 30k + 35k repay

    # Collateral seized = repay_usd * (1 + bonus) / price = 35_000 * 1.05 / 42_000
    seized = 35_000 * 1.05 / 42_000
    assert liquidator.balances[wbtc] == pytest.approx(seized)
    assert bob.balances[wbtc_pool.a_token] == pytest.approx(2 - seized)
    assert wbtc_pool.a_token.total_supply == pytest.approx(2 - seized)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(2 - seized)

    # Liquidator paid exactly the repay amount
    assert liquidator.balances[usdc] == pytest.approx(165_000)

    # No bad debt, HF restored
    assert usdc_pool.bad_debt == pytest.approx(0)
    assert bob.health_factor > 1


def test_liquidation_bonus_value_transferred(env_setup):
    """The USD value of seized collateral equals repay value scaled by the bonus."""
    env = env_setup["env"]
    bob = env_setup["bob"]
    wbtc = env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 42_000.0

    liquidator.liquidate(usdc_pool, bob, 30_000, collateral_pool=wbtc_pool)

    seized_value = liquidator.balances[wbtc] * env.prices["WBTC"]
    assert seized_value == pytest.approx(30_000 * (1 + wbtc_pool.liquidation_bonus))


def test_liquidation_improves_health_factor(env_setup):
    """
    While collateral value still exceeds the debt, a liquidation raises the
    borrower's HF even if it does not immediately clear the shortfall.
    """
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 39_000.0  # underwater; collateral 78k still > debt 70k
    hf_before = bob.health_factor
    assert hf_before < 1

    liquidator.liquidate(usdc_pool, bob, 35_000, collateral_pool=wbtc_pool)

    assert bob.health_factor > hf_before
    assert usdc_pool.bad_debt == pytest.approx(0)


# ============================================================
# BAD DEBT: creation, identification, accounting
# ============================================================

def test_realize_bad_debt_noop_while_collateral_remains(env_setup):
    """realize_bad_debt() must do nothing while the wallet still has collateral."""
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 42_000.0  # underwater but collateral remains

    bob.realize_bad_debt()

    assert usdc_pool.bad_debt == pytest.approx(0)
    assert bob.balances[usdc_pool.v_token] == pytest.approx(70_000)
    assert bob.balances[wbtc_pool.a_token] == pytest.approx(2)


def test_repeated_liquidation_creates_and_accounts_bad_debt(env_setup):
    """
    Deeply underwater borrower: repeated liquidations drain all collateral while
    USDC debt remains. The uncollectable remainder is written off (vTokens burned)
    and booked to usdc_pool.bad_debt. Conservation: repaid + bad_debt == debt.
    """
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    initial_debt = usdc_pool.get_actual_borrow_balance(bob)

    env.prices["WBTC"] = 30_000.0  # collateral 60k << debt 70k
    assert bob.health_factor < 1

    rounds, total_repaid = liquidate_until_clear(
        liquidator, usdc_pool, bob, wbtc_pool, usdc
    )
    assert rounds >= 2  # closing factor forces several passes

    # Debt position fully gone (repaid + written off)
    assert bob.balances.get(usdc_pool.v_token, 0) == pytest.approx(0)
    assert usdc_pool.v_token.total_supply == pytest.approx(0)
    assert usdc_pool.total_scaled_borrow == pytest.approx(0, abs=1e-9)
    assert bob.health_factor == float("inf")

    # Collateral fully seized
    assert bob.balances.get(wbtc_pool.a_token, 0) == pytest.approx(0, abs=1e-9)
    assert wbtc_pool.a_token.total_supply == pytest.approx(0, abs=1e-9)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(0, abs=1e-9)
    assert liquidator.balances[wbtc] == pytest.approx(2)

    # Bad debt correctly identified and booked
    assert usdc_pool.bad_debt > 0
    assert usdc_pool.bad_debt == pytest.approx(initial_debt - total_repaid)
    assert total_repaid + usdc_pool.bad_debt == pytest.approx(initial_debt)


def test_bad_debt_with_interest_accrual(env_setup):
    """
    Interest grows bob's debt for a year, then WBTC collapses. Liquidation clears
    the (now larger) debt, the shortfall is booked as bad debt, and the pool
    treasury is untouched by the liquidation process itself.
    """
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc = env_setup["usdc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)

    env.advance_blocks(env.blocks_per_year)  # interest accrues
    debt_after_interest = usdc_pool.get_actual_borrow_balance(bob)
    assert debt_after_interest > 70_000  # debt grew
    assert usdc_pool.borrow_index > 1.0

    treasury_before = usdc_pool.treasury

    env.prices["WBTC"] = 25_000.0  # collateral 50k << grown debt
    assert bob.health_factor < 1

    rounds, total_repaid = liquidate_until_clear(
        liquidator, usdc_pool, bob, wbtc_pool, usdc
    )
    assert rounds >= 1

    # Position cleared
    assert bob.balances.get(usdc_pool.v_token, 0) == pytest.approx(0)
    assert bob.balances.get(wbtc_pool.a_token, 0) == pytest.approx(0, abs=1e-9)
    assert usdc_pool.total_scaled_borrow == pytest.approx(0, abs=1e-9)

    # Bad debt equals the debt (with interest) minus what was actually repaid
    assert usdc_pool.bad_debt > 0
    assert usdc_pool.bad_debt == pytest.approx(debt_after_interest - total_repaid)

    # Liquidation must not mint/burn treasury reserves
    assert usdc_pool.treasury == pytest.approx(treasury_before)


def test_full_writeoff_when_collateral_nearly_worthless(env_setup):
    """
    A single liquidation call when collateral is almost worthless: it repays only
    the tiny amount the collateral can back, then realize_bad_debt() writes off
    essentially the entire remaining debt.
    """
    env = env_setup["env"]
    bob = env_setup["bob"]
    wbtc = env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 100.0  # 2 WBTC now worth $200
    assert bob.health_factor < 1

    liquidator.liquidate(usdc_pool, bob, 35_000, collateral_pool=wbtc_pool)

    # Collateral can back at most 200 / (1 + bonus) of debt
    max_backable = 2 * 100 / (1 + wbtc_pool.liquidation_bonus)
    assert usdc_pool.bad_debt == pytest.approx(70_000 - max_backable)

    assert bob.balances.get(usdc_pool.v_token, 0) == pytest.approx(0)
    assert bob.balances.get(wbtc_pool.a_token, 0) == pytest.approx(0, abs=1e-9)
    assert usdc_pool.v_token.total_supply == pytest.approx(0)
    assert usdc_pool.total_scaled_borrow == pytest.approx(0, abs=1e-9)
    assert wbtc_pool.a_token.total_supply == pytest.approx(0, abs=1e-9)
    assert liquidator.balances[wbtc] == pytest.approx(2)


def test_health_factor_zero_then_full_writeoff_when_price_is_zero(env_setup):
    """
    Collateral price at zero: HF is 0 (debt, no collateral value), no collateral
    can be seized, and the whole debt is written off as bad debt in one call.
    """
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 0.0

    assert bob.health_factor == 0.0

    liquidator.liquidate(usdc_pool, bob, 35_000, collateral_pool=wbtc_pool)

    # Entire debt written off; nothing seized or paid
    assert usdc_pool.bad_debt == pytest.approx(70_000)
    assert bob.balances.get(usdc_pool.v_token, 0) == pytest.approx(0)
    assert usdc_pool.total_scaled_borrow == pytest.approx(0, abs=1e-9)
    assert liquidator.balances[usdc] == pytest.approx(200_000)
    assert liquidator.balances.get(wbtc, 0) == pytest.approx(0)
    # worthless aTokens remain with bob (no collateral was seizable)
    assert bob.balances[wbtc_pool.a_token] == pytest.approx(2)


def test_realize_bad_debt_is_idempotent(env_setup):
    """Calling realize_bad_debt() again after a write-off changes nothing."""
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc = env_setup["usdc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    open_bob_position(env_setup, borrow_usdc=70_000)
    env.prices["WBTC"] = 100.0
    liquidate_until_clear(liquidator, usdc_pool, bob, wbtc_pool, usdc)

    bad_debt_after_first = usdc_pool.bad_debt
    scaled_borrow_after_first = usdc_pool.total_scaled_borrow

    bob.realize_bad_debt()
    bob.realize_bad_debt()

    assert usdc_pool.bad_debt == pytest.approx(bad_debt_after_first)
    assert usdc_pool.total_scaled_borrow == pytest.approx(scaled_borrow_after_first)


def test_bad_debt_accumulates_across_borrowers(env_setup):
    """Bad debt from independent borrowers sums in the pool's bad_debt ledger."""
    env = env_setup["env"]
    bob = env_setup["bob"]
    usdc, wbtc = env_setup["usdc"], env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    # alice supplies plenty of USDC
    usdc_pool.supply(env_setup["alice"], 150_000)

    # bob: 2 WBTC collateral, borrows 70k
    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 70_000)

    # dave: 2 WBTC collateral, borrows 60k
    dave = Wallet(env, "dave")
    wbtc.mint(dave, 2)
    wbtc_pool.supply(dave, 2)
    usdc_pool.borrow(dave, 60_000)

    env.prices["WBTC"] = 100.0  # both collapse
    assert bob.health_factor < 1
    assert dave.health_factor < 1

    _, bob_repaid = liquidate_until_clear(liquidator, usdc_pool, bob, wbtc_pool, usdc)
    _, dave_repaid = liquidate_until_clear(liquidator, usdc_pool, dave, wbtc_pool, usdc)

    expected = (70_000 - bob_repaid) + (60_000 - dave_repaid)
    assert usdc_pool.bad_debt == pytest.approx(expected)
    assert usdc_pool.bad_debt > 0
    assert usdc_pool.total_scaled_borrow == pytest.approx(0, abs=1e-9)
    assert wbtc_pool.available_liquidity_cash == pytest.approx(0, abs=1e-9)


# ============================================================
# LIQUIDATION CANDIDATE IDENTIFICATION
# ============================================================

def test_get_liquidation_candidates_identifies_only_underwater_wallets(env_setup):
    """
    get_liquidation_candidates() returns exactly the wallets with HF < 1 --
    excluding healthy borrowers and lenders with no debt.
    """
    env = env_setup["env"]
    alice, bob = env_setup["alice"], env_setup["bob"]
    wbtc = env_setup["wbtc"]
    usdc_pool, wbtc_pool = env_setup["usdc_pool"], env_setup["wbtc_pool"]
    liquidator = env_setup["liquidator"]

    usdc_pool.supply(alice, 200_000)  # alice: lender, no debt

    wbtc_pool.supply(bob, 2)
    usdc_pool.borrow(bob, 70_000)     # bob: borrows near his limit

    charlie = Wallet(env, "charlie")
    wbtc.mint(charlie, 2)
    wbtc_pool.supply(charlie, 2)
    usdc_pool.borrow(charlie, 20_000)  # charlie: conservative borrow

    env.prices["WBTC"] = 44_000.0
    assert bob.health_factor < 1
    assert charlie.health_factor > 1

    candidates = liquidator.get_liquidation_candidates()

    assert bob in candidates
    assert charlie not in candidates
    assert alice not in candidates
    assert liquidator not in candidates
