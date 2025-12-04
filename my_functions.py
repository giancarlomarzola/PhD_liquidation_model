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


def plot_column(
    data,
    columns_to_plot,
    secondary_columns=[],
    figsize=(8, 5),
    dpi=100,
    ylabel=None,
    ylabel2=None,
    xlabel="lastUpdateTimestamp",
    title=None,
    save_path=None,
    show_plot=True
):
    # --- Handle input data ---
    if isinstance(columns_to_plot, str):
        columns_to_plot = [columns_to_plot]

    if isinstance(data, str):
        # data is a symbol; load using create_token_df
        symbol = data
        all_columns = ["symbol", "blockNumber", "lastUpdateTimestamp"] + columns_to_plot + secondary_columns
        df = create_token_df(symbol, columns=all_columns).sort_values(by="blockNumber")
        plot_title = title or symbol
    elif isinstance(data, pd.DataFrame):
        # data is an already-loaded dataframe
        df = data.copy()
        plot_title = title or ""
    else:
        raise TypeError("data must be either a token symbol (str) or a pandas DataFrame")

    # ---- Plot ----
    fig, ax1 = plt.subplots(figsize=figsize, dpi=dpi)

    # Primary series
    for col in columns_to_plot:
        ax1.plot(df["lastUpdateTimestamp"], df[col], label=col)

    # Axis labels
    ax1.set_xlabel(xlabel)

    if ylabel:
        ax1.set_ylabel(ylabel)
    else:
        base_col = columns_to_plot[0]
        if "USD" in base_col:
            ax1.set_ylabel("USD amount")
        elif "Currency" in base_col:
            ax1.set_ylabel("Currency amount")
        else:
            ax1.set_ylabel("Token amount")

    ax1.set_title(plot_title)

    # ---- Secondary y-axis ----
    ax2 = None
    if secondary_columns:
        ax2 = ax1.twinx()
        for col in secondary_columns:
            ax2.plot(df["lastUpdateTimestamp"], df[col], linestyle='--', label=f"{col} (secondary)")

        if ylabel2:
            ax2.set_ylabel(ylabel2)
        else:
            ax2.set_ylabel("secondary")

    # ---- Vertical zero-liquidity markers ----
    for zero_col in ["availableLiquidity_USD", "availableLiquidity"]:
        if zero_col in df.columns:
            zero_times = df.loc[df[zero_col] == 0, "lastUpdateTimestamp"]
            for t in zero_times:
                ax1.axvline(x=t, color='gray', linestyle=':', alpha=0.7)

    # ---- Y-axis formatting ----
    axes = [ax1] + ([ax2] if ax2 else [])
    for axis in axes:
        axis.yaxis.set_major_formatter(ScalarFormatter(useOffset=False))
        axis.ticklabel_format(style='plain', axis='y')

        ymin, ymax = axis.get_ylim()
        axis.yaxis.set_major_formatter(
            plt.FuncFormatter(
                lambda x, _: f'{x:,.2f}' if (ymax - ymin) > 0.5 else f'{x:,.4f}'
            )
        )

        if ymin <= 0 <= ymax:
            axis.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

    # ---- Combine legends ----
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message='Creating legend with loc="best" can be slow with large amounts of data.',
            category=UserWarning
        )

        lines, labels = ax1.get_legend_handles_labels()
        if ax2:
            sec_lines, sec_labels = ax2.get_legend_handles_labels()
            lines += sec_lines
            labels += sec_labels

        ax1.legend(lines, labels)

        # ---- Save ----
        if save_path:
            plt.savefig(save_path, bbox_inches='tight')

        if show_plot:
            plt.show()

        plt.close(fig)



def list_to_spreadsheet(lst, n_cols=5):
    """
    Convert a list into a pandas DataFrame with n_cols columns.

    Items are filled row-wise.
    """
    n_rows = math.ceil(len(lst) / n_cols)
    # Pad the list with None if it doesn't divide evenly
    padded_list = lst + [None] * (n_rows * n_cols - len(lst))

    # Split into rows
    rows = [padded_list[i * n_cols:(i + 1) * n_cols] for i in range(n_rows)]

    # Create DataFrame
    df = pd.DataFrame(rows)
    return df
