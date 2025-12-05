import sys
import math
import polars as pl
import pandas as pd
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter
import warnings


def create_token_df(aave_data_path, symbol, columns=None):

    # Handle columns argument
    if columns is None:
        select_cols = None        # load all columns
    else:
        if isinstance(columns, str):
            columns = [columns]
        for col in ["symbol", "blockNumber"]:
            if col not in columns:
                columns.insert(0, col)
        select_cols = columns

    # Load + filter
    df = (
        pl.scan_parquet(str(aave_data_path/"reserves_part_*.parquet"))
        .filter(pl.col("symbol") == symbol)
    )

    # Optional select
    if select_cols is not None:
        df = df.select(select_cols)

    # Execute
    out = df.collect().to_pandas()
    out.sort_values("blockNumber", inplace=True)

    return out



