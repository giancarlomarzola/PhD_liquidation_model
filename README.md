# Aave-Like Defi Lending Protocol
A python implementation of a decentralised overcollateralised lending protocol inspired by Aave. 
The protocol enables simulated users to deposit assets, earn yield, borrow against collateral, and be liquidated when undercollateralized.
The purpose of this model is to assess liquidity risk on such protocols.

## Setup (uv)
This project uses **uv** (https://docs.astral.sh/uv/) for Python package management.
To create a virtual environment for this project:
### 1. Install uv

```bash
curl -Ls https://astral.sh/uv/install.sh | sh
```

Or via pip:

```bash
pip install uv
```

### 2. Sync dependencies

From the project root directory, run:

```bash
uv sync
```

This will:

- Create a virtual environment (if it does not already exist)
- Install dependencies from `pyproject.toml`
- Use the lockfile (`uv.lock`) if present