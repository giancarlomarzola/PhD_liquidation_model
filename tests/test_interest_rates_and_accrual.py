import pytest
from environment.defi_env import DefiEnv, Token, LendingPool, Wallet
from environment.parameters import pool_parameters


# ========================================================================================================================
# FIXTURES
# ========================================================================================================================

@pytest.fixture
def env():
    """Create a fresh DeFi environment for each test."""
    return DefiEnv(prices={"usdc": 1.0, "wbtc": 50_000.0})


@pytest.fixture
def usdc_pool(env):
    """Create USDC lending pool with standard parameters."""
    usdc = Token(env, "usdc")
    pool = LendingPool(env=env, underlying_token=usdc, **pool_parameters["usdc"])
    return pool


@pytest.fixture
def wbtc_pool(env):
    """Create WBTC lending pool with standard parameters."""
    wbtc = Token(env, "wbtc")
    pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
    return pool


@pytest.fixture
def supplier(env, usdc_pool):
    """Create a supplier wallet."""
    wallet = Wallet(env, "supplier")
    usdc_pool.underlying_token.mint(wallet, 100_000)
    return wallet


@pytest.fixture
def borrower(env, wbtc_pool):
    """Create a borrower wallet with WBTC collateral."""
    wallet = Wallet(env, "borrower")
    wbtc_pool.underlying_token.mint(wallet, 10)
    return wallet


# ========================================================================================================================
# BORROW RATE TESTS
# ========================================================================================================================

class TestBorrowRate:
    """Tests for borrow rate calculation at different utilisation ratios."""

    def test_borrow_rate_at_zero_utilisation(self, usdc_pool):
        """Borrow rate at exactly 0% utilisation should equal base rate."""
        assert usdc_pool.usage_ratio == 0
        borrow_rate = usdc_pool.borrow_rate
        assert abs(borrow_rate - usdc_pool.interest_base_rate) < 1e-10

    def test_borrow_rate_at_optimal_utilisation(self, env, supplier, usdc_pool):
        """Borrow rate at exactly optimal utilisation equals base_rate + slope_1."""
        supplier.supply(usdc_pool, 100_000)
        
        # Borrow up to optimal utilisation
        optimal_borrow = 100_000 * usdc_pool.optimal_usage_ratio
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, optimal_borrow)
        
        assert abs(usdc_pool.usage_ratio - usdc_pool.optimal_usage_ratio) < 1e-6
        expected_rate = usdc_pool.interest_base_rate + usdc_pool.interest_slope_1
        actual_rate = usdc_pool.borrow_rate
        assert abs(actual_rate - expected_rate) < 1e-10

    def test_borrow_rate_above_optimal_uses_slope_2(self, env, supplier, usdc_pool):
        """Borrow rate above optimal utilisation should use slope_2 (kink point)."""
        supplier.supply(usdc_pool, 100_000)
        
        # Borrow above optimal utilisation
        borrow_amount = 100_000 * 0.9  # 90% utilisation
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, borrow_amount)
        
        assert usdc_pool.usage_ratio > usdc_pool.optimal_usage_ratio
        
        # Rate should be: base + slope_1 + (excess / (1 - u_opt)) * slope_2
        u = usdc_pool.usage_ratio
        u_opt = usdc_pool.optimal_usage_ratio
        excess = (u - u_opt) / (1 - u_opt)
        expected_rate = (
            usdc_pool.interest_base_rate 
            + usdc_pool.interest_slope_1 
            + excess * usdc_pool.interest_slope_2
        )
        actual_rate = usdc_pool.borrow_rate
        assert abs(actual_rate - expected_rate) < 1e-10

    def test_borrow_rate_at_100_percent_utilisation(self, env, supplier, usdc_pool):
        """Borrow rate at 100% utilisation should be maximum (stress scenario)."""
        supplier.supply(usdc_pool, 100_000)
        
        # Borrow exactly available liquidity
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 100_000)
        
        assert abs(usdc_pool.usage_ratio - 1.0) < 1e-6
        
        # Rate should be maximum
        u = 1.0
        u_opt = usdc_pool.optimal_usage_ratio
        excess = (u - u_opt) / (1 - u_opt)
        expected_rate = (
            usdc_pool.interest_base_rate 
            + usdc_pool.interest_slope_1 
            + excess * usdc_pool.interest_slope_2
        )
        actual_rate = usdc_pool.borrow_rate
        assert abs(actual_rate - expected_rate) < 1e-6


# ========================================================================================================================
# RESERVE FACTOR TESTS
# ========================================================================================================================

class TestReserveFactor:
    """Tests for reserve factor and treasury accrual."""

    def test_reserve_factor_flows_to_treasury(self, env, supplier, usdc_pool):
        """A portion of borrow interest equal to reserve_rate flows to treasury."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 50_000)
        
        initial_treasury = usdc_pool.treasury
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        
        treasury_increase = usdc_pool.treasury - initial_treasury
        assert treasury_increase > 0
        
        # Treasury should be reserve_rate * total_borrow_interest
        total_debt_before = 50_000
        borrow_rate = usdc_pool.borrow_rate
        total_supply_before = 100_000
        supply_rate = usdc_pool.supply_rate
        borrow_factor = (1 + borrow_rate) ** (1) - 1  # Simplified for 1 year
        supply_factor = (1 + supply_rate) ** (1) - 1
        expected_treasury_increase = total_debt_before * borrow_factor - total_supply_before * supply_factor
        
        # Allow for some rounding error
        assert abs(treasury_increase - expected_treasury_increase) / expected_treasury_increase < 0.05

    def test_supply_rate_less_than_borrow_rate(self, env, supplier, usdc_pool):
        """Supply rate should be less than borrow rate (due to reserve factor)."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 50_000)
        
        borrow_rate = usdc_pool.borrow_rate
        supply_rate = usdc_pool.supply_rate
        
        # With reserve_rate > 0, supply_rate < borrow_rate
        assert supply_rate < borrow_rate
        assert supply_rate > 0

    def test_reserve_factor_zero_supply_equals_borrow(self, env):
        """With reserve_rate = 0, supply rate should equal borrow rate (adjusted for utilisation)."""
        usdc = Token(env, "usdc")
        pool = LendingPool(
            env=env, 
            underlying_token=usdc,
            interest_slope_1=0.07,
            interest_slope_2=0.3,
            interest_base_rate=0.02,
            optimal_usage_ratio=0.8,
            reserve_rate=0.0,  # No reserve
            max_ltv=0.75,
            liquidation_bonus=0.045,
            liquidation_threshold=0.78,
            closing_factor=0.5
        )
        
        supplier = Wallet(env, "supplier")
        usdc.mint(supplier, 100_000)
        supplier.supply(pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(pool, 50_000)
        
        borrow_rate = pool.borrow_rate
        supply_rate = pool.supply_rate
        expected_supply_rate = borrow_rate * pool.usage_ratio * (1 - pool.reserve_rate)
        
        assert abs(supply_rate - expected_supply_rate) < 1e-10

    def test_reserve_factor_one_supply_rate_zero(self, env):
        """With reserve_rate = 1.0, supply rate should be 0 (all interest goes to treasury)."""
        usdc = Token(env, "usdc")
        pool = LendingPool(
            env=env, 
            underlying_token=usdc,
            interest_slope_1=0.07,
            interest_slope_2=0.3,
            interest_base_rate=0.02,
            optimal_usage_ratio=0.8,
            reserve_rate=1.0,  # All to treasury
            max_ltv=0.75,
            liquidation_bonus=0.045,
            liquidation_threshold=0.78,
            closing_factor=0.5
        )
        
        supplier = Wallet(env, "supplier")
        usdc.mint(supplier, 100_000)
        supplier.supply(pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(pool, 50_000)
        
        supply_rate = pool.supply_rate
        assert abs(supply_rate) < 1e-10  # Should be 0


# ========================================================================================================================
# SUPPLY RATE TESTS
# ========================================================================================================================

class TestSupplyRate:
    """Tests for supply rate calculation."""

    def test_supply_rate_with_zero_borrows(self, supplier, usdc_pool):
        """Supply rate with 0 borrows should be 0."""
        supplier.supply(usdc_pool, 100_000)
        
        assert usdc_pool.usage_ratio == 0
        assert usdc_pool.supply_rate == 0

    def test_supply_rate_always_less_than_equal_borrow_rate(self, env, supplier, usdc_pool):
        """Supply rate should always be <= borrow rate."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        
        # Test at various borrow levels
        for borrow_amount in [10_000, 30_000, 50_000, 80_000]:
            borrower.borrow(usdc_pool, borrow_amount)
            assert usdc_pool.supply_rate <= usdc_pool.borrow_rate
            borrower.repay(usdc_pool, borrow_amount)


# ========================================================================================================================
# ACCRUAL MECHANICS TESTS
# ========================================================================================================================

class TestAccrualMechanics:
    """Tests for interest accrual correctness and mechanics."""

    def test_interest_accrues_over_multiple_blocks(self, env, supplier, usdc_pool):
        """Interest should accrue correctly over multiple blocks."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 50_000)
        
        initial_borrow_index = usdc_pool.borrow_index
        initial_debt = usdc_pool.get_actual_borrow_balance(borrower)
        
        env.advance_blocks(100)
        
        new_borrow_index = usdc_pool.borrow_index
        new_debt = usdc_pool.get_actual_borrow_balance(borrower)
        
        assert new_borrow_index > initial_borrow_index
        assert new_debt > initial_debt

    def test_interest_accrues_proportionally(self, env, supplier, usdc_pool):
        """Two blocks should accrue approximately 2x one block."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 50_000)
        
        # Advance 1 year
        initial_index = usdc_pool.borrow_index
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        one_year_index = usdc_pool.borrow_index
        one_year_growth = one_year_index - initial_index
        
        # Reset and advance 2 years
        env2 = DefiEnv(prices={"usdc": 1.0, "wbtc": 50_000.0})
        usdc2 = Token(env2, "usdc")
        pool2 = LendingPool(env=env2, underlying_token=usdc2, **pool_parameters["usdc"])
        supplier2 = Wallet(env2, "supplier2")
        usdc2.mint(supplier2, 100_000)
        supplier2.supply(pool2, 100_000)
        
        borrower2 = Wallet(env2, "borrower2")
        wbtc2 = Token(env2, "wbtc")
        wbtc_pool2 = LendingPool(env=env2, underlying_token=wbtc2, **pool_parameters["wbtc"])
        borrower2.balances[wbtc2] = 10
        borrower2.supply(wbtc_pool2, 10)
        borrower2.borrow(pool2, 50_000)
        
        initial_index2 = pool2.borrow_index
        env2.advance_blocks(2 * pool2.env.blocks_per_year)
        two_year_index = pool2.borrow_index
        two_year_growth = two_year_index - initial_index2
        
        # Two years should be approximately 2x one year (allow 5% tolerance for rate changes)
        ratio = two_year_growth / one_year_growth
        assert 1.9 < ratio < 2.1

    def test_two_equal_borrows_accrue_equally(self, env, supplier, usdc_pool):
        """Two equal borrows should accrue the same interest over the same period."""
        supplier.supply(usdc_pool, 200_000)
        
        borrower1 = Wallet(env, "borrower1")
        borrower2 = Wallet(env, "borrower2")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        
        for b in [borrower1, borrower2]:
            b.balances[wbtc] = 10
            b.supply(wbtc_pool, 10)
            b.borrow(usdc_pool, 50_000)
        
        initial_debt1 = usdc_pool.get_actual_borrow_balance(borrower1)
        initial_debt2 = usdc_pool.get_actual_borrow_balance(borrower2)
        assert abs(initial_debt1 - initial_debt2) < 1e-6
        
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        
        final_debt1 = usdc_pool.get_actual_borrow_balance(borrower1)
        final_debt2 = usdc_pool.get_actual_borrow_balance(borrower2)
        
        interest1 = final_debt1 - initial_debt1
        interest2 = final_debt2 - initial_debt2
        
        assert abs(interest1 - interest2) / interest1 < 0.001  # Within 0.1%

    def test_larger_borrow_accrues_more_interest(self, env, supplier, usdc_pool):
        """A larger borrow should accrue proportionally more interest."""
        supplier.supply(usdc_pool, 200_000)
        
        borrower1 = Wallet(env, "borrower1")
        borrower2 = Wallet(env, "borrower2")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        
        for b in [borrower1, borrower2]:
            b.balances[wbtc] = 10
            b.supply(wbtc_pool, 10)
        
        borrower1.borrow(usdc_pool, 30_000)
        borrower2.borrow(usdc_pool, 60_000)
        
        initial_debt1 = usdc_pool.get_actual_borrow_balance(borrower1)
        initial_debt2 = usdc_pool.get_actual_borrow_balance(borrower2)
        
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        
        final_debt1 = usdc_pool.get_actual_borrow_balance(borrower1)
        final_debt2 = usdc_pool.get_actual_borrow_balance(borrower2)
        
        interest1 = final_debt1 - initial_debt1
        interest2 = final_debt2 - initial_debt2
        
        # Interest on 60k should be ~2x interest on 30k
        ratio = interest2 / interest1
        assert 1.95 < ratio < 2.05

    def test_supplier_receives_correct_interest(self, env, supplier, usdc_pool):
        """Supplier should receive interest corresponding to supply rate."""
        initial_supplied = 100_000
        supplier.supply(usdc_pool, initial_supplied)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 50_000)
        
        initial_supply_index = usdc_pool.supply_index
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        final_supply_index = usdc_pool.supply_index
        
        # Supplier's actual supply should have grown
        final_actual_supply = usdc_pool.get_actual_supply_balance(supplier)
        expected_supply = initial_supplied * (final_supply_index / initial_supply_index)
        
        assert abs(final_actual_supply - expected_supply) < 1e-6


# ========================================================================================================================
# EDGE CASES
# ========================================================================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_utilisation_no_accrual(self, env, supplier, usdc_pool):
        """Interest accrual at 0% utilisation should leave balances unchanged."""
        supplier.supply(usdc_pool, 100_000)
        
        initial_supply_index = usdc_pool.supply_index
        initial_borrow_index = usdc_pool.borrow_index
        
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        
        # With 0 borrows, supply index should not change
        assert abs(usdc_pool.supply_index - initial_supply_index) < 1e-10
        assert abs(usdc_pool.borrow_index - initial_borrow_index) < 1e-10

    def test_borrow_rate_non_negative(self, usdc_pool):
        """Borrow rate should never be negative."""
        assert usdc_pool.borrow_rate >= 0
        assert usdc_pool.interest_base_rate >= 0

    def test_very_small_borrow_precision(self, env, supplier, usdc_pool):
        """Very small borrow over many blocks should maintain precision."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 0.01)  # Very small borrow
        
        initial_debt = usdc_pool.get_actual_borrow_balance(borrower)
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        final_debt = usdc_pool.get_actual_borrow_balance(borrower)
        
        # Should have accrued some interest
        assert final_debt > initial_debt
        # But interest rate should still be calculable
        assert usdc_pool.borrow_rate >= 0


# ========================================================================================================================
# INTEGRATION TESTS
# ========================================================================================================================

class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_partial_repayment_leaves_residual_debt(self, env, supplier, usdc_pool):
        """Repaying only principal should leave residual v_token debt equal to accrued interest."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        
        borrow_amount = 50_000
        borrower.borrow(usdc_pool, borrow_amount)
        
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        
        actual_debt = usdc_pool.get_actual_borrow_balance(borrower)
        accrued_interest = actual_debt - borrow_amount
        
        # Mint additional USDC to borrower for interest repayment
        usdc_pool.underlying_token.mint(borrower, borrow_amount)
        
        # Repay only principal
        borrower.repay(usdc_pool, borrow_amount)
        
        remaining_actual_debt = usdc_pool.get_actual_borrow_balance(borrower)
        
        # Remaining debt should approximately equal accrued interest
        assert abs(remaining_actual_debt - accrued_interest) / accrued_interest < 0.01

    def test_full_repayment_clears_debt(self, env, supplier, usdc_pool):
        """Full repayment including interest should clear all debt."""
        supplier.supply(usdc_pool, 100_000)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        
        borrow_amount = 50_000
        borrower.borrow(usdc_pool, borrow_amount)
        
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        
        actual_debt = usdc_pool.get_actual_borrow_balance(borrower)
        
        # Mint additional USDC for interest
        usdc_pool.underlying_token.mint(borrower, actual_debt)
        
        # Repay full amount
        borrower.repay(usdc_pool, actual_debt)
        
        final_debt = usdc_pool.get_actual_borrow_balance(borrower)
        assert abs(final_debt) < 1e-6

    def test_supplier_withdrawal_receives_interest(self, env, supplier, usdc_pool):
        """Supplier withdrawing after interest accrual should receive more than deposited."""
        initial_supply = 100_000
        supplier.supply(usdc_pool, initial_supply)
        
        borrower = Wallet(env, "borrower")
        wbtc = Token(env, "wbtc")
        wbtc_pool = LendingPool(env=env, underlying_token=wbtc, **pool_parameters["wbtc"])
        borrower.balances[wbtc] = 10
        borrower.supply(wbtc_pool, 10)
        borrower.borrow(usdc_pool, 50_000)
        
        env.advance_blocks(usdc_pool.env.blocks_per_year)
        
        # Supplier withdraws everything
        actual_supply = usdc_pool.get_actual_supply_balance(supplier)
        supplier.withdraw(usdc_pool, actual_supply)
        
        withdrawn_amount = supplier.balances.get(usdc_pool.underlying_token, 0.0)
        
        # Should have withdrawn more than initially supplied
        assert withdrawn_amount > initial_supply