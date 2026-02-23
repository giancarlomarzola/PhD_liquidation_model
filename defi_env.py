from __future__ import annotations


# To worry about later:
    # Creating the users so that overall there is a given LTV distribution, for given token pairs
    # Discretionary activity rate
    # Token price series generation
    # Figuring out what parameters to use for simulation

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
        tokens: dict[str, Token] | None = None, # use token symbol as key
        prices: dict[str, float] | None = None, # price at given block
        wallets: dict[str, Wallet] | None = None, # Wallets present on the blockchain
        lending_pools: dict[str, LendingPool] | None = None,
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
        self.prices = prices

    # Properties: state_summary, prices, 
    # Methods: update_prices, act_update_react


class Wallet:
    def __init__(
        self,
        env: DefiEnv,
        name: str,
        balances: dict[Token, float] | None = None,
        is_liquidator: bool=False
    ):
        # Add Wallet to defi environment
        assert name not in env.wallets, f"User {name} exists"
        self.env = env
        self.env.wallets[name] = self

        # set starting funds
        if balances is None:
            balances = {}
        self.balances = balances

        self.name = name
        self.is_liquidator = is_liquidator
    
    # Properties: || wealth, max_borrowable_value, 
    # Methods: initialise_transaction, get_liquidation_candidates 
    # Maybe: helper method to request supply_withdraw from wallet, instead of calling it from pool

    def __str__(self) -> str:
        indent = "    "
        balances_str = "\n".join(
            f"{indent*2}{token.symbol:<15}{amount:>15,.4f}"
            for token, amount in self.balances.items()
        ) if self.balances else f"{indent*2}None"
        return (
            f"{self.name} Wallet\n"
            f"{'-'*50}\n"
            f"{indent}Liquidator: {self.is_liquidator}\n"
            f"{indent}Balances:\n"
            f"{balances_str}"
            f"\n"
        )

    @property
    def total_collateral_usd(self):
        total = 0.0
        for token, amount in self.balances.items():
            if isinstance(token, aToken):
                pool = token.pool
                total += amount * pool.underlying_token.price * pool.max_ltv
        return total
    
    @property
    def total_supplied_usd(self):
        total = 0.0
        for token, amount in self.balances.items():
            if isinstance(token, aToken):
                pool = token.pool
                total += amount * pool.underlying_token.price
        return total

    @property
    def total_borrowed_usd(self):
        total=0.0
        for token, amount in self.balances.items():
            if isinstance(token, vToken):
                pool = token.pool
                total += amount * pool.underlying_token.price
        return total

    @property
    def available_collateral_usd(self):
        return self.total_collateral_usd - self.total_borrowed_usd


class Token:
    def __init__(
        self,
        env: DefiEnv,
        symbol: str,
        total_supply: float=0
        # Should i also keep track of who holds how much?
    ):
        # Add Token to defi environment
        assert symbol not in env.tokens, f"Token {symbol} exists"
        self.env = env
        self.env.tokens[symbol] = self

        self.symbol = symbol
        self.total_supply = total_supply

    # Methods: mint, burn, transfer
    def __repr__(self):
        return self.symbol

    @property
    def price(self):
        return self.env.prices.get(self.symbol, None)
    
    def mint(self, wallet: Wallet, amount: float):
        assert amount > 0
        self.total_supply += amount
        wallet.balances[self] = wallet.balances.get(self, 0.0) + amount

    def burn(self, wallet: Wallet, amount: float):
        assert amount > 0
        wallet_balance = wallet.balances.get(self, 0.0)
        assert wallet_balance >= amount, f"Wallet does not have enough {self.symbol} to burn"
        self.total_supply -= amount
        wallet.balances[self] -= amount


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
        interest_rate: float, # TODO: change to borrow and supply rate
        reserve_rate: float,
        max_ltv: float,                 # how much of supply can be used as collateral
        liquidation_bonus: float,       # reward for liquidator (aka liquidation_penalty)
        liquidation_threshold: float,   # threshold at which liquidation can be initialised
        closing_factor: float,          # maximum % of position that can be liquidated in one transaction
        a_token: Token | None = None,
        v_token: Token | None = None,
    ):

        # Add Lending Pool to defi environment
        assert underlying_token.symbol not in env.lending_pools, f"Lending Pool {underlying_token.symbol} exists"
        self.env = env
        self.env.lending_pools[underlying_token.symbol] = self

        self.underlying_token = underlying_token
        self.a_token = aToken(self.env, f"a_{underlying_token.symbol}", self)
        self.v_token = vToken(self.env, f"v_{underlying_token.symbol}", self)
        self.interest_rate = interest_rate
        self.reserve_rate = reserve_rate
        self.max_ltv = max_ltv
        self.liquidation_bonus = liquidation_bonus
        self.liquidation_threshold = liquidation_threshold
        self.closing_factor = closing_factor
        
    # Properties: bad_debt, utilisation_rate, supply_rate, borrow_rate
    # Methods: supply, withdraw, borrow, repay, update_borrow_lend_rates, accrue_interest, liquidate

    def __str__(self) -> str:
        indent = "    "  # 4 spaces
        return (
            f"{self.underlying_token.symbol.upper()} LENDING POOL "
            f"(block {self.env.blocknumber})\n"
            f"{'-'*50}\n"
            f"{indent}{'aToken Supply:':25}{self.a_token.total_supply:>15,.2f}\n"
            f"{indent}{'vToken Supply:':25}{self.v_token.total_supply:>15,.2f}\n"
            f"{indent}{'Utilisation Rate:':25}{self.utilisation_rate*100:>14.2f}%\n"
            f"{indent}{'Interest Rate:':25}{self.interest_rate*100:>14.2f}%\n"
            f"\n"
            f"{indent}{'Reserve Rate:':25}{self.reserve_rate*100:>14.2f}%\n"
            f"{indent}{'Max LTV:':25}{self.max_ltv*100:>14.2f}%\n"
            f"{indent}{'Liquidation Bonus:':25}{self.liquidation_bonus*100:>14.2f}%\n"
            f"{indent}{'Liquidation Threshold:':25}{self.liquidation_threshold*100:>14.2f}%\n"
            f"{indent}{'Closing Factor:':25}{self.closing_factor*100:>14.2f}%\n"
        )
    @property
    def available_liquidity(self):
        return(self.a_token.total_supply - self.v_token.total_supply)
    
    @property
    def utilisation_rate(self):
        if self.v_token.total_supply == 0 or self.a_token.total_supply==0:
            utilisation_rate = 0
        else:
            utilisation_rate = self.v_token.total_supply / self.a_token.total_supply
        return(max(0, utilisation_rate))

    def _transfer(self, wallet: Wallet, token: Token, amount: float, from_wallet: bool):
        assert amount > 0, "Amount must be positive"
        wallet_balance = wallet.balances.get(token, 0.0)
        if from_wallet is True:
            assert wallet_balance >= amount, f"Wallet does not have enough {token.symbol}"
            wallet.balances[token] -= amount
        else:
            # TODO: Check collateral is sufficient after transaction
            wallet.balances[token] = wallet_balance + amount

    def supply(self, wallet: Wallet, amount: float):
        self._transfer(wallet, self.underlying_token, amount, from_wallet=True)
        self.a_token.mint(wallet, amount)

    def withdraw(self, wallet: Wallet, amount: float):
        assert self.available_liquidity >= amount, "Not enough liquidity in pool to withdraw"
        self._transfer(wallet, self.underlying_token, amount, from_wallet=False)
        self.a_token.burn(wallet, amount)

    def borrow(self, wallet: Wallet, amount: float):
        assert self.available_liquidity >= amount, "Not enough liquidity in pool to borrow"
        self._transfer(wallet, self.underlying_token, amount, from_wallet=False)
        self.v_token.mint(wallet, amount)

    def repay(self, wallet: Wallet, amount: float):
        self._transfer(wallet, self.underlying_token, amount, from_wallet=True)
        self.v_token.burn(wallet, amount)



# ================================================================================================================================
# Basic test example
# Market with 2 tokens (USDC, WBTC)
# ================================================================================================================================

# TODO: Add second person so Alice supplies usdc/borrows wbtc and Bob supplies wbtc/borrows usdc

# parameters - later: maybe keep dictionary with these parameters for each token i use so i can easily access them for testing
max_ltv = 0.73
liquidation_threshold = 0.78
liquidation_bonus = 0.05
closing_factor = 0.5


defi_env = DefiEnv(prices={"usdc":1.01, "wbtc":50000})

usdc = Token(defi_env, "usdc")
wbtc = Token(defi_env, "wbtc")

usdc_pool = LendingPool(
    env=defi_env, 
    underlying_token=usdc, 
    interest_rate=0.03, 
    reserve_rate=0.2, 
    max_ltv=max_ltv, 
    liquidation_bonus=liquidation_bonus, 
    liquidation_threshold=liquidation_threshold, 
    closing_factor=closing_factor)
wbtc_pool = LendingPool(
    env=defi_env, 
    underlying_token=wbtc, 
    interest_rate=0.003, 
    reserve_rate=0.2, 
    max_ltv=max_ltv, 
    liquidation_bonus=liquidation_bonus, 
    liquidation_threshold=liquidation_threshold, 
    closing_factor=closing_factor)

# Create users
Alice = Wallet(defi_env, "alice")
Bob = Wallet(defi_env, "bob")

# Provide initial wallet funds
usdc.mint(Alice, 50_000)
#wbtc.mint(Alice, 0.01)

#usdc.mint(Bob, 0.1)
wbtc.mint(Bob, 2)


# Initial supplies
print(
    f"{'='*50}\n"
    "Initial state\n"
    f"{'='*50}\n"
    )
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)

print(
    f"{'='*50}\n"
    "Supplies to each pool\n"
    f"{'='*50}\n"
    )
usdc_pool.supply(Alice, 50_000)
wbtc_pool.supply(Bob, 2)
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)

print(
    f"{'='*50}\n"
    "Borrows from each pool\n"
    f"{'='*50}\n"
    )
usdc_pool.borrow(Bob, 20_000)
wbtc_pool.borrow(Alice, 1)
print(Alice)
print(Bob)
print(usdc_pool)
print(wbtc_pool)


print(
    f"{'='*50}\n"
    "Repay the borrowed amount from each pool\n"
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