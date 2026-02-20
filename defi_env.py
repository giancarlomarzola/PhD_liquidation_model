from __future__ import annotations


# To worry about later:
    # Creating the users so that overall there is a given LTV distribution, for given token pairs
    # Discretionary activity rate
    # Token price series generation
    # Figuring out what parameters to use for simulation

class DefiEnv:
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
        return(
            f"{self.name} Wallet State\n"
            + f"\tBalances: {self.balances}\n"
            + f"\tIs Liquidator: {self.is_liquidator}"
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
        if self not in wallet.balances:
            wallet.balances[self] = 0.0
        wallet.balances[self] += amount

    def burn(self, wallet: Wallet, amount: float):
        assert amount > 0
        balance = wallet.balances.get(self, 0.0)
        assert balance >= amount, f"Wallet does not have enough {self.symbol} to burn"
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
        
    # Properties: bad_debt, utilisation_rate
    # Methods: supply, withdraw, borrow, repay, update_borrow_lend_rates, accrue_interest, liquidate

    def __str__(self) -> str:
        return(
            f"{self.underlying_token.symbol} Pool State at block {self.env.blocknumber}\n"
            + f"\ta_token Supply: {self.a_token.total_supply:.2f}"
            + f"\tv_token Supply: {self.v_token.total_supply:.2f}"
            + f"\tUtilisation Rate: {self.utilisation_rate*100:.2f}%"
            + f"\tInterest Rate: {self.interest_rate*100:.2f}%\n"
            + f"\tLiquidation Parameters: \t max_ltv = {self.max_ltv*100:.2f}%, liquidation_bonus = {self.liquidation_bonus*100:.2f}%, "
            + f"liquidation_threshold = {self.liquidation_threshold*100:.2f}%, closing_factor = {self.closing_factor*100:.2f}%"
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
            wallet.balances[token] += amount

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

Alice = Wallet(defi_env, "alice")

usdc.mint(Alice, 50_000)
wbtc.mint(Alice, 0.1)

print("\nInitial state")
print(Alice)
print(usdc_pool)

print("\nSupply 20k")
usdc_pool.supply(Alice, 20_000)
print(Alice)
print(usdc_pool)

print("\nWithdraw 5k")
usdc_pool.withdraw(Alice, 5_000)
print(Alice)
print(usdc_pool)

print("\nBorrow 10k")
usdc_pool.borrow(Alice, 10_000)
print(Alice)
print(usdc_pool)

print(f"\nTotal Supplied: {Alice.total_supplied_usd}\n"
    + f"Total Collateral: {Alice.total_collateral_usd}\n"
    + f"Total Debt: {Alice.total_borrowed_usd}\n"
    + f"Available Collateral: {Alice.available_collateral_usd}"
    )

print("\nRepay 10k")
usdc_pool.repay(Alice, 10_000)
print(Alice)
print(usdc_pool)

print("\nWithdraw full a_usdc amount")
usdc_pool.withdraw(Alice, Alice.balances.get(usdc_pool.a_token))
print(Alice)
print(usdc_pool)