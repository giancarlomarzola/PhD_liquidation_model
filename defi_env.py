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
        balances: dict[str, float] | None = None,
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
    
    # Properties: allowed_collateral || wealth, borrow_value, supply_value, max_borrowable_value, 
    # Methods: initialise_transaction, get_liquidation_candidates 
    # Maybe: helper method to request supply_withdraw from wallet, instead of calling it from pool


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
    @property
    def price(self):
        return self.env.prices.get(self.symbol, None)
    
    def mint(self, wallet: Wallet, amount: float):
        assert amount > 0
        self.total_supply += amount
        if self.symbol not in wallet.balances:
            wallet.balances[self.symbol] = 0.0
        wallet.balances[self.symbol] += amount

    def burn(self, wallet: Wallet, amount: float):
        assert amount > 0
        balance = wallet.balances.get(self.symbol, 0.0)
        assert balance >= amount, f"Wallet does not have enough {self.symbol} to burn"
        self.total_supply -= amount
        wallet.balances[self.symbol] -= amount


class LendingPool:
    def __init__(
        self,
        env: DefiEnv,
        underlying_token: Token,
        total_supplied: float,
        total_borrowed: float,
        interest_rate: float,
        reserve_rate: float,
        max_ltv: float,                 # how much of supply can be used as collateral
        liquidation_bonus: float,       # reward for liquidator (aka liquidation_penalty)
        liquidation_threshold: float,   # threshold at which liquidation can be initialised
        closing_factor: float,          # maximum % of position that can be liquidated in one transaction
        a_token: Token | None = None,
        v_token: Token | None = None,
    ):

        # Create a_token and v_token for underlying
        if a_token is None:
            a_token = Token(env, f"a_{underlying_token.symbol}")
        if v_token is None:
            v_token = Token(env, f"v_{underlying_token.symbol}")

        self.env = env
        self.underlying_token = underlying_token
        self.a_token = a_token
        self.v_token = v_token
        self.total_supplied = total_supplied
        self.total_borrowed = total_borrowed
        self.interest_rate = interest_rate
        self.reserve_rate = reserve_rate
        self.max_ltv = max_ltv
        self.liquidation_bonus = liquidation_bonus
        self.liquidation_threshold = liquidation_threshold
        self.closing_factor = closing_factor
        
    # Properties: bad_debt, utilisation_rate
    # Methods: supply, withdraw, borrow, repay, update_borrow_lend_rates, accrue_interest, liquidate

    def supply(self, wallet: Wallet, amount: float):
        # Check requirements
        assert amount > 0, "Amount must be positive"
        balance = wallet.balances.get(self.underlying_token.symbol, 0.0)
        assert balance >= amount, f"Wallet does not have enough {self.symbol} to supply"

        # take token amount from wallet
        wallet.balances[self.underlying_token.symbol] -= amount

        # mint a_token to wallet
        self.a_token.mint(wallet, amount)

        # add token amount to total_supplied
        self.total_supplied += amount

    def withdraw(self, wallet: Wallet, amount: float):
        # check requirements
        assert amount > 0, "Amount must be positive"
        balance = wallet.balances.get(self.a_token.symbol, 0.0)
        assert balance - amount >= 0, f"Wallet does not have enough {self.a_token.symbol} to withdraw"
        # TODO: Check that withdrawal does not reduce LTV too much

        # return token amount to wallet
        wallet.balances[self.underlying_token.symbol] += amount

        # take a_token from wallet
        self.a_token.burn(wallet, amount)

        # remove token amount from total_supplied
        self.total_supplied -= amount

    def borrow(self, wallet: Wallet, amount: float):
        # check requirements
        assert amount > 0, "Amount must be positive"
        available_liquidity = self.total_supplied - self.total_borrowed
        assert available_liquidity >= amount, "Not enough liquidity in pool to borrow"
        # TODO: check how much the wallet is allowed to borrow

        # Take token amount from wallet
        wallet.balances[self.underlying_token.symbol] -= amount

        # mint v_token to wallet
        self.v_token.mint(wallet, amount)

        # Add token amount to pool's total_borrowed
        self.total_borrowed += amount
    
    def repay(self, wallet: Wallet, amount: float):
        # check requirements
        assert amount > 0, "Amount must be positive"
        balance = wallet.balances.get(self.v_token.symbol, 0.0)
        assert balance - amount >= 0, f"Wallet does not have enough {self.v_token.symbol} to repay"

        # return token amount to wallet
        wallet.balances[self.underlying_token.symbol] += amount

        # take v_token from wallet
        self.v_token.burn(wallet, amount)

        # remove token amount from total_borrowed
        self.total_borrowed -= amount



# ================================================================================================================================
# Basic test example
# Market with 2 tokens (USDC, WBTC)
# ================================================================================================================================

# parameters - later: maybe keep dictionary with these parameters for each token i use so i can easily access them for testing
max_ltv = 0.73
liquidation_threshold = 0.78
liquidation_bonus = 0.05
closing_factor = 0.5


defi_env = DefiEnv()

usdc = Token(defi_env, "usdc")
wbtc = Token(defi_env, "wbtc")

usdc_pool = LendingPool(defi_env, usdc, 0, 0, 0.03, 0.001, max_ltv, liquidation_bonus, liquidation_threshold, closing_factor)
wbtc_pool = LendingPool(defi_env, wbtc, 0, 0, 0.003, 0.0001, max_ltv, liquidation_bonus, liquidation_threshold, closing_factor)

Alice = Wallet(defi_env, "alice")

usdc.mint(Alice, 50_000)
wbtc.mint(Alice, 0.1)

print("Alice balances: ", Alice.balances)
print("USDC pool - Supplied: ", usdc_pool.total_supplied, "Borrowed: ", usdc_pool.total_borrowed)

usdc_pool.supply(Alice, 20_000)
print("Alice balances: ", Alice.balances)
print("USDC pool - Supplied: ", usdc_pool.total_supplied, "Borrowed: ", usdc_pool.total_borrowed)

usdc_pool.withdraw(Alice, 5_000)
print("Alice balances: ", Alice.balances)
print("USDC pool - Supplied: ", usdc_pool.total_supplied, "Borrowed: ", usdc_pool.total_borrowed)

usdc_pool.borrow(Alice, 7_000)
print("Alice balances: ", Alice.balances)
print("USDC pool - Supplied: ", usdc_pool.total_supplied, "Borrowed: ", usdc_pool.total_borrowed)

usdc_pool.repay(Alice, 7_000)
print("Alice balances: ", Alice.balances)
print("USDC pool - Supplied: ", usdc_pool.total_supplied, "Borrowed: ", usdc_pool.total_borrowed)

usdc_pool.withdraw(Alice, Alice.balances.get("a_usdc"))
print("Alice balances: ", Alice.balances)
print("USDC pool - Supplied: ", usdc_pool.total_supplied, "Borrowed: ", usdc_pool.total_borrowed)