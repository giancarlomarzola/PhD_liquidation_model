from __future__ import annotations
from environment.parameters import pool_parameters


class DefiEnv:
    """
    Global simulation environment representing the DeFi system state.

    Acts as an abstract blockchain layer coordinating
    tokens, wallets, and lending pools. It maintains global state variables
    such as block number and asset prices, and provides the shared context
    within which all agents and protocols interact.

    It is the single source of truth for the market-wide state
    and is responsible for advancing time and propagating price updates
    through the system.

    Responsibilities
    ----------------
    - Registry of all tokens in the system
    - Registry of all wallets (agents)
    - Registry of all lending pools
    - Tracking of current block number
    - Determination of token prices at each block

    Parameters
    ----------
    blocknumber : int, optional
        Initial block number of the simulation.
    tokens : dict[str, Token], optional
        Mapping of token symbol to Token instance.
    prices : dict[str, float], optional
        Mapping of token symbol to current price.
    wallets : dict[str, Wallet], optional
        Mapping of wallet identifier to Wallet instance.
    lending_pools : dict[str, LendingPool], optional
        Mapping of underlying token symbol to LendingPool instance.
    """

    def __init__(
        self,
        blocknumber: int = 0,
        tokens: dict[str, Token] | None = None,
        prices: dict[str, float] | None = None,
        wallets: dict[str, Wallet] | None = None,
        lending_pools: dict[str, LendingPool] | None = None,
        blocks_per_year: int = 2_628_000,
        price_provider = None,  # PriceProvider instance (optional)
    ):
        if tokens is None:
            tokens = {}

        if prices is None:
            prices = {}

        if wallets is None:
            wallets = {}

        if lending_pools is None:
            lending_pools = {}

        self.blocknumber = blocknumber
        self.tokens = tokens
        self.prices = prices
        self.wallets = wallets
        self.lending_pools = lending_pools
        self.blocks_per_year = blocks_per_year
        self.price_provider = price_provider

    # Properties: state_summary, prices,
    # Methods: advance_blocks

    # What it doesn't do (this should be done by the simulation, not the environment):
    #   - Arbitrary user transactions
    #   - User reactions to changes
    #   - Liquidations

    def advance_blocks(self, num_blocks: int, new_prices: dict[str, float] | None = None):
        """
        Advance the simulation by num_blocks.

        Triggers:
        - Block number increment
        - Interest accrual on all pools
        - Price updates (from price_provider or new_prices parameter)

        If price_provider is set, advances it and fetches new prices.
        Otherwise, uses new_prices if provided.
        """
        self.blocknumber += num_blocks

        # Accrue interest on all pools (which recalculates interest rates internally)
        for pool in self.lending_pools.values():
            pool.accrue_interest(num_blocks)

        # Update prices from provider or parameter
        if self.price_provider:
            self.price_provider.advance_time(num_blocks)
            self.prices = self.price_provider.get_prices()
        elif new_prices:
            self.prices.update(new_prices)


class Wallet:
    def __init__(
        self,
        env: DefiEnv,
        name: str,
        balances: dict[Token, float] | None = None,
        is_liquidator: bool = False,
    ):
        # Add Wallet to defi environment
        assert name not in env.wallets, f"User {name} exists"
        self.env = env
        self.env.wallets[name] = self
        self.balances = balances or {}
        self.name = name
        self.is_liquidator = is_liquidator

    def __str__(self) -> str:
        indent = "    "
        balances_str = (
            "\n".join(
                f"{indent*2}{token.symbol:<15}{amount:>15,.4f}"
                for token, amount in self.balances.items()
                if amount != 0
            )
            if any(amount != 0 for amount in self.balances.values())
            else f"{indent*2}None"
        )
        return (
            f"{self.name} Wallet\n"
            f"{'-'*50}\n"
            f"{indent}Liquidator: {self.is_liquidator}\n"
            f"{indent}Balances:\n"
            f"{balances_str}\n"
            f"{indent}Health Factor: {self.health_factor:.4f}\n"
        )

    @property
    def total_supplied_usd(self):
        total = 0.0
        for token, amount in self.balances.items():
            if isinstance(token, aToken):
                pool = token.pool
                actual_amount = amount * pool.supply_index
                total += actual_amount * pool.underlying_token.price
        return total

    @property
    def total_borrowed_usd(self):
        total = 0.0
        for token, amount in self.balances.items():
            if isinstance(token, vToken):
                pool = token.pool
                actual_amount = amount * pool.borrow_index
                total += actual_amount * pool.underlying_token.price
        return total

    @property
    def total_collateral_usd(self):
        total = 0.0
        for token, amount in self.balances.items():
            if isinstance(token, aToken):
                pool = token.pool
                actual_amount = amount * pool.supply_index
                total += actual_amount * pool.underlying_token.price * pool.max_ltv
        return total

    @property
    def available_collateral_usd(self):
        return self.total_collateral_usd - self.total_borrowed_usd

    @property
    def health_factor(self) -> float:
        """
        Aave-style health factor using total_collateral_usd and total_borrowed_usd.
        HF = (Total Collateral Value * Weighted Average Liquidation Threshold) / Total Borrow Value
        """
        total_collateral = self.total_collateral_usd
        total_borrowed = self.total_borrowed_usd

        if total_borrowed == 0:
            return float("inf")

        # Compute weighted average liquidation threshold
        weighted_liquidation_threshold_sum = 0.0
        for token, amount in self.balances.items():
            if isinstance(token, aToken):
                pool = token.pool
                actual_amount = amount * pool.supply_index
                collateral_value = actual_amount * pool.underlying_token.price * pool.max_ltv
                weighted_liquidation_threshold_sum += (
                    collateral_value * pool.liquidation_threshold
                )

        weighted_avg_liquidation_threshold = (
            weighted_liquidation_threshold_sum / total_collateral
            if total_collateral > 0
            else 0
        )

        return (total_collateral * weighted_avg_liquidation_threshold) / total_borrowed

    def health_factor_after(
        self,
        collateral_change: dict[Token, float] | None = None,
        debt_change: dict[Token, float] | None = None,
    ) -> float:
        """
        Calculates the health factor after a given transaction, without executing the transaction.
        Used to determine if the transaction can safely be carried out.
        """

        collateral_change = collateral_change or {}
        debt_change = debt_change or {}

        total_collateral = 0.0
        total_borrowed = 0.0
        weighted_liq_threshold_sum = 0.0

        # Evaluate collateral positions
        for token, amount in self.balances.items():
            if isinstance(token, aToken):
                pool = token.pool
                actual_amount = amount * pool.supply_index
                delta = collateral_change.get(token, 0.0)
                new_actual_amount = actual_amount + delta

                collateral_value = (
                    new_actual_amount * pool.underlying_token.price * pool.max_ltv
                )

                total_collateral += collateral_value
                weighted_liq_threshold_sum += (
                    collateral_value * pool.liquidation_threshold
                )

            elif isinstance(token, vToken):
                pool = token.pool
                actual_amount = amount * pool.borrow_index
                delta = debt_change.get(token, 0.0)
                total_borrowed += (actual_amount + delta) * pool.underlying_token.price

        # Handle new debt positions not yet in balances
        for token, delta in debt_change.items():
            if token not in self.balances:
                pool = token.pool
                total_borrowed += delta * pool.underlying_token.price

        if total_borrowed == 0:
            return float("inf")

        weighted_avg_liq_threshold = (
            weighted_liq_threshold_sum / total_collateral if total_collateral > 0 else 0
        )

        return (total_collateral * weighted_avg_liq_threshold) / total_borrowed

    # Helper functions to trigger supply, withdraw, borrow, repay from Wallet instead of LendingPool
    def supply(self, pool: LendingPool, amount: float):
        pool.supply(self, amount)

    def withdraw(self, pool: LendingPool, amount: float):
        pool.withdraw(self, amount)

    def borrow(self, pool: LendingPool, amount: float):
        pool.borrow(self, amount)

    def repay(self, pool: LendingPool, amount: float):
        pool.repay(self, amount)

    def get_liquidation_candidates(self) -> list[Wallet]:
        """Returns all wallets in the environment with health factor < 1."""
        return [
            wallet
            for wallet in self.env.wallets.values()
            if wallet is not self and wallet.health_factor < 1
        ]

    # Helper function to trigger liquidation from liquidator's Wallet instead of LendingPool
    def liquidate(
        self,
        pool: LendingPool,
        borrower: Wallet,
        amount: float,
        collateral_pool: LendingPool | None = None,
    ):
        pool.liquidate(self, borrower, amount, collateral_pool)


class Token:
    def __init__(
        self,
        env: DefiEnv,
        symbol: str,
        total_supply: float = 0,
        # Should i also keep track of who holds how much?
    ):
        # Add Token to defi environment
        assert symbol not in env.tokens, f"Token {symbol} exists"
        self.env = env
        self.env.tokens[symbol] = self
        self.symbol = symbol
        self.total_supply = total_supply

    def __repr__(self):
        return self.symbol

    @property
    def price(self):
        return self.env.prices.get(self.symbol, None)

    def mint(self, wallet: Wallet, amount: float):
        assert amount > 0, "Amount must be positive"
        wallet_balance = wallet.balances.get(self, 0.0)
        self.total_supply = self.total_supply + amount
        wallet.balances[self] = wallet_balance + amount

    def burn(self, wallet: Wallet, amount: float):
        assert amount > 0, "Amount must be positive"
        wallet_balance = wallet.balances.get(self, 0.0)
        assert (
            wallet_balance >= amount
        ), f"Wallet {wallet.name} does not have enough {self.symbol} to burn"
        self.total_supply = self.total_supply - amount
        wallet.balances[self] = wallet_balance - amount

    def transfer(self, sender: Wallet, receiver: Wallet, amount: float):
        assert amount > 0, "Amount must be positive"
        sender_balance = sender.balances.get(self, 0.0)
        assert sender_balance >= amount, "Insufficient balance"
        sender.balances[self] = sender_balance - amount
        receiver.balances[self] = receiver.balances.get(self, 0.0) + amount


class aToken(Token):
    def __init__(self, env, symbol, pool):
        super().__init__(env, symbol)
        self.pool = pool


class vToken(Token):
    def __init__(self, env, symbol, pool):
        super().__init__(env, symbol)
        self.pool = pool


class LendingPool:
    def __init__(
        self,
        env: DefiEnv,
        underlying_token: Token,
        interest_slope_1: float,  # slope of interest rate before optimal usage ratio
        interest_slope_2: float,  # slope of interest rate after optimal usage ratio
        interest_base_rate: float,  # minimum interest rate amount, slope amounts are added to this
        optimal_usage_ratio: float,  # kink-point of interest rate curve
        reserve_rate: float,  # proportion of borrow interest that is sent to treasury upon repayment, instead of paid out to suppliers
        max_ltv: float,  # proportion of a user's supplied amount that can be used as collateral
        liquidation_bonus: float,  # reward for liquidator (aka liquidation_penalty)
        liquidation_threshold: float,  # threshold at which liquidation can be initialised, reflected in health factor
        closing_factor: float,  # maximum % of position that can be liquidated in one transaction
        supply_cap: float | None = None,
        borrow_cap: float | None = None,
        # a_token and v_token: automatically created by pool
        # available_liquidity_cash: initialised as 0, to start with different amount it has to be transferred in or minted
        # bad_debt: initialised as 0 (same as above)
        # treasury: initialised as 0 (same as above)
    ):
        # Add Lending Pool to defi environment
        assert (
            underlying_token.symbol not in env.lending_pools
        ), f"Lending Pool {underlying_token.symbol} exists"
        self.env = env
        self.env.lending_pools[underlying_token.symbol] = self
        # Initialise tokens
        self.underlying_token = underlying_token
        a_symbol = f"a_{underlying_token.symbol}"
        v_symbol = f"v_{underlying_token.symbol}"
        assert a_symbol not in env.tokens, f"Token {a_symbol} already exists"
        assert v_symbol not in env.tokens, f"Token {v_symbol} already exists"
        self.a_token = aToken(env, a_symbol, self)
        self.v_token = vToken(env, v_symbol, self)
        # Risk and interest parameters
        self.interest_slope_1 = interest_slope_1
        self.interest_slope_2 = interest_slope_2
        self.interest_base_rate = interest_base_rate
        self.optimal_usage_ratio = optimal_usage_ratio
        self.reserve_rate = reserve_rate
        self.max_ltv = max_ltv
        self.liquidation_bonus = liquidation_bonus
        self.liquidation_threshold = liquidation_threshold
        self.closing_factor = closing_factor
        # Initialise balances at 0
        self.available_liquidity_cash: float = 0
        self.bad_debt: float = 0
        self.treasury: float = 0
        self.supply_cap = supply_cap
        self.borrow_cap = borrow_cap
        # Interest indices (start at 1.0, grow with accrued interest)
        self.supply_index: float = 1.0
        self.borrow_index: float = 1.0
        # Track scaled balances (actual_amount = scaled_balance * index)
        self.total_scaled_supply: float = 0.0
        self.total_scaled_borrow: float = 0.0

    def __str__(self) -> str:
        indent = "    "  # 4 spaces
        total_actual_supply = self.total_scaled_supply * self.supply_index
        total_actual_borrow = self.total_scaled_borrow * self.borrow_index
        return (
            f"{self.underlying_token.symbol.upper()} LENDING POOL "
            f"(block {self.env.blocknumber})\n"
            f"{'-'*50}\n"
            f"{indent}{'Actual Supply (aTokens):':25}{total_actual_supply:>15,.2f}\n"
            f"{indent}{'Supply Index:':25}{self.supply_index:>15,.6f}\n"
            f"{indent}{'Actual Borrows (vTokens):':25}{total_actual_borrow:>15,.2f}\n"
            f"{indent}{'Borrow Index:':25}{self.borrow_index:>15,.6f}\n"
            f"{indent}{'Available Liquidity (Cash)':25}{self.available_liquidity_cash:>15,.2f}\n"
            f"{indent}{'Usage Ratio:':25}{self.usage_ratio*100:>14.2f}%\n"
            f"{indent}{'Borrow Rate:':25}{self.borrow_rate*100:>14.2f}%\n"
            f"{indent}{'Supply Rate:':25}{self.supply_rate*100:>14.2f}%\n"
            f"\n"
            f"{indent}{'Reserve Rate:':25}{self.reserve_rate*100:>14.2f}%\n"
            f"{indent}{'Supply Cap:':25}{f'{self.supply_cap:,.2f}' if self.supply_cap is not None else 'None':>14}\n"
            f"{indent}{'Borrow Cap:':25}{f'{self.borrow_cap:,.2f}' if self.borrow_cap is not None else 'None':>14}\n"
            f"{indent}{'Max LTV:':25}{self.max_ltv*100:>14.2f}%\n"
            f"{indent}{'Liquidation Bonus:':25}{self.liquidation_bonus*100:>14.2f}%\n"
            f"{indent}{'Liquidation Threshold:':25}{self.liquidation_threshold*100:>14.2f}%\n"
            f"{indent}{'Closing Factor:':25}{self.closing_factor*100:>14.2f}%\n"
        )

    @property
    def usage_ratio(self):
        total_debt = self.total_scaled_borrow * self.borrow_index
        total_liquidity = self.available_liquidity_cash + total_debt

        if total_liquidity == 0:
            return 0

        return total_debt / total_liquidity

    def _get_scaled_supply_balance(self, wallet: Wallet) -> float:
        """Get a wallet's scaled (underlying) supply balance."""
        return wallet.balances.get(self.a_token, 0.0)
    
    def get_actual_supply_balance(self, wallet: Wallet) -> float:
        """Get a wallet's actual supply balance (scaled balance * supply index)."""
        return self._get_scaled_supply_balance(wallet) * self.supply_index

    def _get_scaled_borrow_balance(self, wallet: Wallet) -> float:
        """Get a wallet's scaled (underlying) borrow balance."""
        return wallet.balances.get(self.v_token, 0.0)
    
    def get_actual_borrow_balance(self, wallet: Wallet) -> float:
        """Get a wallet's actual borrow balance (scaled balance * borrow index)."""
        return self._get_scaled_borrow_balance(wallet) * self.borrow_index

    def _transfer_from_wallet(self, wallet: Wallet, amount: float):
        # Helper function to handle transfers from Wallet to LendingPool
        assert amount > 0, "Amount must be positive"
        wallet_balance = wallet.balances.get(self.underlying_token, 0.0)
        assert (
            wallet_balance >= amount
        ), f"Wallet '{wallet.name}' does not have enough {self.underlying_token.symbol}"
        wallet.balances[self.underlying_token] = wallet_balance - amount
        self.available_liquidity_cash += amount

    def _transfer_from_pool(self, wallet: Wallet, amount: float):
        assert amount > 0, "Amount must be positive"
        assert (
            self.available_liquidity_cash >= amount
        ), f"{self.underlying_token.symbol} pool does not have enough liquidity"
        self.available_liquidity_cash -= amount
        wallet.balances[self.underlying_token] = (
            wallet.balances.get(self.underlying_token, 0.0) + amount
        )

    def supply(self, wallet: Wallet, amount: float):
        if self.supply_cap:
            total_actual_supply = self.total_scaled_supply * self.supply_index
            assert (
                total_actual_supply + amount
            ) <= self.supply_cap, "Transaction exceeds pool's supply cap"
        self._transfer_from_wallet(wallet, amount)
        # Mint scaled aTokens: scaled_amount = amount / supply_index
        scaled_amount = amount / self.supply_index
        self.a_token.mint(wallet, scaled_amount)
        self.total_scaled_supply += scaled_amount

    def withdraw(self, wallet: Wallet, amount: float):
        assert amount > 0, "Amount must be positive"
        hf_after = wallet.health_factor_after(collateral_change={self.a_token: -amount})
        assert (  # Check HF
            hf_after > 1
        ), f"Withdraw would cause liquidation risk -- Health factor after transaction = {hf_after}"
        actual_balance = self.get_actual_supply_balance(wallet)
        assert (  # Check that user isn't withdrawing more than they supplied
            actual_balance >= amount
        ), f"Wallet '{wallet.name}' does not have sufficient {self.a_token.symbol} for transaction"
        self._transfer_from_pool(wallet, amount)
        # Burn scaled aTokens
        scaled_amount = amount / self.supply_index
        self.a_token.burn(wallet, scaled_amount)
        self.total_scaled_supply -= scaled_amount

    def borrow(self, wallet: Wallet, amount: float):
        assert amount > 0, "Amount must be positive"
        if self.borrow_cap:
            total_actual_borrow = self.total_scaled_borrow * self.borrow_index
            assert (
                total_actual_borrow + amount
            ) <= self.borrow_cap, "Transaction exceeds pool's borrow cap"
        hf_after = wallet.health_factor_after(debt_change={self.v_token: amount})
        assert (  # Check HF
            hf_after > 1
        ), f"Borrow would cause liquidation risk -- Health factor after transaction = {hf_after}"
        self._transfer_from_pool(wallet, amount)
        # Mint scaled vTokens: scaled_amount = amount / borrow_index
        scaled_amount = amount / self.borrow_index
        self.v_token.mint(wallet, scaled_amount)
        self.total_scaled_borrow += scaled_amount

    def repay(self, wallet: Wallet, amount: float):
        assert amount > 0, "Amount must be positive"
        actual_balance = self.get_actual_borrow_balance(wallet)
        assert (  # Check that user isn't repaying more than they borrowed
            actual_balance >= amount
        ), f"Wallet '{wallet.name}' does not have sufficient {self.v_token.symbol} for transaction"
        self._transfer_from_wallet(wallet, amount)
        # Burn scaled vTokens
        scaled_amount = amount / self.borrow_index
        self.v_token.burn(wallet, scaled_amount)
        self.total_scaled_borrow -= scaled_amount

    def calculate_interest_rates(self) -> tuple[float, float]:
        """
        Aave-style kinked interest rate model.

        Returns
        -------
        tuple[float, float]
            (borrow_rate, supply_rate) as annualised rates.
        """
        u = self.usage_ratio
        u_opt = self.optimal_usage_ratio

        if u <= u_opt:
            borrow_rate = self.interest_base_rate + (u / u_opt) * self.interest_slope_1
        else:
            excess = (u - u_opt) / (1 - u_opt)
            borrow_rate = (
                self.interest_base_rate
                + self.interest_slope_1
                + excess * self.interest_slope_2
            )

        supply_rate = borrow_rate * u * (1 - self.reserve_rate)
        return borrow_rate, supply_rate

    @property
    def borrow_rate(self) -> float:
        return self.calculate_interest_rates()[0]

    @property
    def supply_rate(self) -> float:
        return self.calculate_interest_rates()[1]

    def accrue_interest(self, blocks_elapsed: int):
        """
        Accrues interest by updating supply and borrow indices.
        Does not mint/burn tokens; instead updates exchange rates.
        Treasury receives the reserve_rate portion of borrow interest.
        """
        if blocks_elapsed <= 0:
            return

        borrow_rate, supply_rate = self.calculate_interest_rates()
        blocks_per_year = self.env.blocks_per_year

        # Calculate interest using OLD indices (before they grow)
        total_actual_borrow = self.total_scaled_borrow * self.borrow_index
        total_actual_supply = self.total_scaled_supply * self.supply_index

        # Calculate growth factors
        borrow_factor = (1 + borrow_rate) ** (blocks_elapsed / blocks_per_year) - 1
        supply_factor = (1 + supply_rate) ** (blocks_elapsed / blocks_per_year) - 1

        # Calculate interest accrued
        borrow_interest = total_actual_borrow * borrow_factor
        supply_interest = total_actual_supply * supply_factor

        # Update indices (these grow monotonically)
        self.borrow_index *= (1 + borrow_factor)
        self.supply_index *= (1 + supply_factor)

        # Treasury receives the difference between what borrowers pay and what suppliers receive
        self.treasury += borrow_interest - supply_interest

    # TODO: Review entire liquidate function to ensure it works as intended
    def liquidate(
        self,
        liquidator: Wallet,
        borrower: Wallet,
        repay_amount: float,
        collateral_pool: LendingPool,
    ):
        # Check borrower health factor
        assert borrower.health_factor < 1, (
            f"Borrower '{borrower.name}' is not undercollateralized "
            f"(HF = {borrower.health_factor:.4f})"
        )

        # Check repay amount does not exceed amount allowed by closing factor
        max_repay = self.get_actual_borrow_balance(borrower) * self.closing_factor
        assert repay_amount <= max_repay, (
            f"Repay amount ({repay_amount:.4f}) exceeds closing factor maximum "
            f"({max_repay:.4f})"
        )

        # Check liquidator has sufficient funds for repay
        assert liquidator.balances.get(self.underlying_token, 0.0) >= repay_amount, (
            f"Liquidator '{liquidator.name}' has insufficient "
            f"{self.underlying_token.symbol} (need {repay_amount:.4f})"
        )

        # Calculate collateral to seize (repay USD value + liquidation bonus)
        repay_usd = repay_amount * self.underlying_token.price
        collateral_price = collateral_pool.underlying_token.price
        collateral_to_seize = (
            repay_usd * (1 + self.liquidation_bonus) / collateral_price
        )

        # Cap at borrower's actual collateral balance
        borrower_actual_collateral = collateral_pool.get_actual_supply_balance(borrower)
        actual_collateral_seized = min(collateral_to_seize, borrower_actual_collateral)

        # Check pool has available cash to pay out collateral as underlying
        assert collateral_pool.available_liquidity_cash >= actual_collateral_seized, (
            f"Collateral pool has insufficient cash "
            f"({collateral_pool.available_liquidity_cash:.4f}) "
            f"to pay out {actual_collateral_seized:.4f}"
        )

        # Execute liquidation: liquidator repays borrower's debt
        self._transfer_from_pool(liquidator, repay_amount)
        # Burn scaled vTokens
        scaled_repay = repay_amount / self.borrow_index
        self.v_token.burn(borrower, scaled_repay)
        self.total_scaled_borrow -= scaled_repay

        # Execute liquidation: burn borrower's scaled aTokens, send underlying to liquidator
        scaled_collateral = actual_collateral_seized / collateral_pool.supply_index
        collateral_pool.a_token.burn(borrower, scaled_collateral)
        collateral_pool.total_scaled_supply -= scaled_collateral
        collateral_pool._transfer_from_pool(liquidator, actual_collateral_seized)

        # Account any resulting bad debt (collateral insufficient to cover full bonus)
        if actual_collateral_seized < collateral_to_seize:
            shortfall_usd = (
                collateral_to_seize - actual_collateral_seized
            ) * collateral_price
            self.bad_debt += shortfall_usd / self.underlying_token.price


# ========================================================================================================================
# Liquidation example with interest accrual
# Market with 2 tokens (USDC, WBTC)
#
# Scenario:
#   - Alice is a USDC liquidity provider and liquidator
#   - Bob supplies WBTC as collateral and borrows USDC
#   - 1 year passes, interest accrues
#   - WBTC price crashes, pushing Bob's health factor below 1
#   - Alice liquidates Bob: repays half of Bob's debt and seizes WBTC collateral at a bonus
# ========================================================================================================================
if __name__ == "__main__":

    def print_current_state():
        print("")
        print(Alice)
        print("")
        print(Bob)
        print("")
        print(usdc_pool)
        print("")
        print(wbtc_pool)

    defi_env = DefiEnv(prices={"usdc": 1.00, "wbtc": 50_000.00})

    usdc = Token(defi_env, "usdc")
    wbtc = Token(defi_env, "wbtc")

    usdc_pool = LendingPool(
        env=defi_env, underlying_token=usdc, **pool_parameters["usdc"]
    )
    wbtc_pool = LendingPool(
        env=defi_env, underlying_token=wbtc, **pool_parameters["wbtc"]
    )

    # Alice: USDC liquidity provider and liquidator
    #   - supplies 75,000 USDC to pool (so Bob can borrow)
    #   - keeps 25,000 USDC in wallet for liquidation
    Alice = Wallet(defi_env, "alice", is_liquidator=True)
    usdc.mint(Alice, 100_000)

    # Bob: WBTC holder who uses it as collateral to borrow USDC
    Bob = Wallet(defi_env, "bob")
    wbtc.mint(Bob, 2)

    print(f"{'='*50}\nInitial state\n{'='*50}\n")
    print_current_state()

    print(
        3 * "\n"
        + f"{'='*50}\nAlice supplies 75,000 USDC; Bob supplies 2 WBTC\n{'='*50}\n"
    )
    Alice.supply(usdc_pool, 75_000)
    Bob.supply(wbtc_pool, 2)
    print_current_state()

    # Bob borrows 50,000 USDC (HF = 2 * 50,000 * 0.73 * 0.78 / 50,000 = 1.14)
    print(3 * "\n" + f"{'='*50}\nBob borrows 50,000 USDC  |  HF = 1.14\n{'='*50}\n")
    Bob.borrow(usdc_pool, 50_000)
    print_current_state()

    # Advance 1 year: interest accrues on supplies and borrows
    blocks_per_year = defi_env.blocks_per_year
    print(
        3 * "\n"
        + f"{'='*50}\nAdvance 1 year ({blocks_per_year} blocks)  |  Interest accrues\n{'='*50}\n"
    )
    defi_env.advance_blocks(blocks_per_year)
    print_current_state()

    # WBTC crashes: HF = 2 * 40,000 * 0.73 * 0.78 / (50,000 * accrued_interest) ≈ undercollateralised
    print(
        3 * "\n"
        + f"{'='*50}\nWBTC price crashes: $50,000 --> $40,000  |  Bob becomes undercollateralised\n{'='*50}\n"
    )
    defi_env.prices["wbtc"] = 40_000.00
    print_current_state()

    # Alice liquidates Bob
    #   Repay amount is capped to closing_factor of Bob's debt, but also to Alice's available balance
    print(
        3 * "\n"
        + f"{'='*50}\nAlice liquidates Bob\n{'='*50}\n"
    )
    actual_bob_debt = usdc_pool.get_actual_borrow_balance(Bob)
    max_repay_by_closing_factor = actual_bob_debt * usdc_pool.closing_factor
    alice_available = Alice.balances.get(usdc, 0.0)
    repay_amount = min(max_repay_by_closing_factor, alice_available)
    Alice.liquidate(usdc_pool, Bob, repay_amount, collateral_pool=wbtc_pool)
    print_current_state()