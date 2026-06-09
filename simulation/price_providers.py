"""Price source abstraction for simulations."""

from abc import ABC, abstractmethod
from typing import Dict
import numpy as np
import pandas as pd
import glob


class PriceProvider(ABC):
    """Abstract base class for price sources."""

    @abstractmethod
    def get_prices(self, block_or_timestamp) -> Dict[str, float]:
        """Return dict mapping token symbol to price at given block/timestamp."""
        pass

    @abstractmethod
    def advance_time(self, blocks: int) -> None:
        """Advance internal time by given number of blocks."""
        pass

    @property
    @abstractmethod
    def current_block(self) -> int:
        """Return current block number."""
        pass


class MockPriceProvider(PriceProvider):
    """
    Fixed or manually-specified prices for testing.
    Can also apply predefined price shocks.
    """

    def __init__(self, initial_prices: Dict[str, float], price_shocks: Dict[int, Dict[str, float]] = None):
        """
        Parameters
        ----------
        initial_prices : dict
            Mapping of token symbol to initial price
        price_shocks : dict, optional
            Mapping of block number to price updates {block: {symbol: price}}
        """
        self.initial_prices = initial_prices.copy()
        self.prices = initial_prices.copy()
        self.price_shocks = price_shocks or {}
        self._current_block = 0

    def get_prices(self, block_or_timestamp=None) -> Dict[str, float]:
        return self.prices.copy()

    def advance_time(self, blocks: int) -> None:
        for _ in range(blocks):
            self._current_block += 1
            if self._current_block in self.price_shocks:
                self.prices.update(self.price_shocks[self._current_block])

    @property
    def current_block(self) -> int:
        return self._current_block


class StochasticPriceProvider(PriceProvider):
    """
    Generate prices using stochastic processes (geometric Brownian motion).
    """

    def __init__(
        self,
        initial_prices: Dict[str, float],
        volatilities: Dict[str, float] = None,
        drifts: Dict[str, float] = None,
        correlation_matrix: np.ndarray = None,
        random_seed: int = None,
    ):
        """
        Parameters
        ----------
        initial_prices : dict
            Starting prices for each token
        volatilities : dict, optional
            Annualized volatility per token (default 0.3)
        drifts : dict, optional
            Annualized drift per token (default 0.0)
        correlation_matrix : ndarray, optional
            Correlation matrix for token returns (only applied if multiple tokens)
        random_seed : int, optional
            Random seed for reproducibility
        """
        self.initial_prices = initial_prices.copy()
        self.prices = initial_prices.copy()
        self.tokens = list(initial_prices.keys())

        if volatilities is None:
            volatilities = {token: 0.3 for token in self.tokens}
        if drifts is None:
            drifts = {token: 0.0 for token in self.tokens}

        self.volatilities = volatilities
        self.drifts = drifts
        self.correlation_matrix = correlation_matrix

        if random_seed is not None:
            np.random.seed(random_seed)

        self._current_block = 0
        self.blocks_per_year = 2_628_000  # Ethereum

    def get_prices(self, block_or_timestamp=None) -> Dict[str, float]:
        return self.prices.copy()

    def advance_time(self, blocks: int) -> None:
        dt = blocks / self.blocks_per_year

        for _ in range(blocks):
            dW = np.random.multivariate_normal(
                mean=np.zeros(len(self.tokens)),
                cov=self.correlation_matrix if self.correlation_matrix is not None else np.eye(len(self.tokens))
            ) * np.sqrt(dt / blocks)

            for i, token in enumerate(self.tokens):
                vol = self.volatilities[token]
                drift = self.drifts[token]

                dS = drift * self.prices[token] * (dt / blocks) + vol * self.prices[token] * dW[i]
                self.prices[token] = max(0.0001, self.prices[token] + dS)

            self._current_block += 1

    @property
    def current_block(self) -> int:
        return self._current_block


class EmpiricalPriceProvider(PriceProvider):
    """
    Load prices from historical Aave parquet files.

    Data structure: parquet files in aave_parquet/ folder with columns:
    - blockNumber
    - symbol
    - priceInMarketReferenceCurrency
    """

    def __init__(self, data_dir: str = None, tokens: list = None, resample_blocks: int = 1,
                 start_block: int = None, end_block: int = None):
        """
        Parameters
        ----------
        data_dir : str, optional
            Path to data directory. Default: data/aave_parquet/ (relative to project root)
        tokens : list, optional
            Tokens to load. If None, loads all available.
        resample_blocks : int, optional
            Interval at which to sample prices (1 = every block, 2 = every 2 blocks, etc.)
        start_block : int, optional
            Start block number (inclusive). Only loads data from this block onward.
        end_block : int, optional
            End block number (inclusive). Only loads data up to this block.
        """
        if data_dir is None:
            from pathlib import Path
            project_root = Path(__file__).parent.parent
            data_dir = str(project_root / "data" / "aave_parquet")

        self.data_dir = data_dir
        self.resample_blocks = resample_blocks
        self.start_block = start_block
        self.end_block = end_block
        self._load_data(tokens)

    def _load_data(self, tokens: list = None) -> None:
        """Load and preprocess parquet files with optional block range filtering."""
        parquet_files = sorted(glob.glob(f"{self.data_dir}/*.parquet"))

        if not parquet_files:
            raise FileNotFoundError(f"No parquet files found in {self.data_dir}")

        dfs = []
        for f in parquet_files:
            # Read only needed columns
            cols = ['blockNumber', 'symbol', 'priceInMarketReferenceCurrency']
            df = pd.read_parquet(f, columns=cols)

            # Apply block range filters
            if self.start_block is not None:
                df = df[df['blockNumber'] >= self.start_block]
            if self.end_block is not None:
                df = df[df['blockNumber'] <= self.end_block]

            dfs.append(df)

        df = pd.concat(dfs, ignore_index=True)

        if tokens:
            df = df[df['symbol'].isin(tokens)]

        df = df[['blockNumber', 'symbol', 'priceInMarketReferenceCurrency']].copy()
        df = df.sort_values('blockNumber').reset_index(drop=True)

        self.min_block = df['blockNumber'].min()
        self.max_block = df['blockNumber'].max()

        self.price_data = df.set_index(['blockNumber', 'symbol'])['priceInMarketReferenceCurrency']
        self.unique_blocks = sorted(df['blockNumber'].unique())

        self._current_idx = 0
        self._current_block = self.min_block

    def get_prices(self, block_or_timestamp=None) -> Dict[str, float]:
        """Get prices at current block, with forward-fill for missing blocks."""
        block = self._current_block

        prices = {}
        for symbol in self.price_data.index.get_level_values('symbol').unique():
            try:
                prices[symbol] = float(self.price_data.loc[block, symbol])
            except KeyError:
                closest_block = max(b for b in self.unique_blocks if b <= block)
                try:
                    prices[symbol] = float(self.price_data.loc[closest_block, symbol])
                except (KeyError, ValueError):
                    prices[symbol] = None

        return {k: v for k, v in prices.items() if v is not None}

    def advance_time(self, blocks: int) -> None:
        """Advance by given blocks (respecting resample_blocks)."""
        for _ in range(blocks):
            self._current_idx = min(
                self._current_idx + self.resample_blocks,
                len(self.unique_blocks) - 1
            )
            self._current_block = self.unique_blocks[self._current_idx]

    @property
    def current_block(self) -> int:
        return self._current_block

    def get_available_tokens(self) -> list:
        """Return list of tokens available in data."""
        return sorted(self.price_data.index.get_level_values('symbol').unique().tolist())

    def get_block_range(self) -> tuple:
        """Return (min_block, max_block) available in data."""
        return self.min_block, self.max_block
