# Classes and their attributes/methods

ctrl+shift+v to see preview


## Simulation

### Attributes
- Number of Users
- Mu (for initial user LTV distribution)
- Sigma (for initial user LTV distribution)
- Discretionary Activity Rate (how many users execute self-initiated transactions) (previosly Participation Proportion)

### Methods
- Step (i.e. proceed to next block)
- Collect Metrics (e.g. Market state, number of bad debt users, amount of bad debt)


## Market

### Attributes
- Block Number
- Supply Token (constant)
- Debt Token (constant)
- Supply Token Price
- Debt Token Price
- Total Supplied Tokens
- Total Borrowed Tokens
- Liquidation Bonus (constant)
- Liquidation Threshold (constant)
- Closing Factor (constant)

### Methods
- Update Prices
- Update Parameters
- Update Total Amounts


## User

### Attributes
- ID
- Supplied Amount (tokens)
- Borrowed Amount (tokens)
- Supplied Amount (usd)
- Borrowed Amount (usd)
- LTV
- Bad debt?

### Methods
- Update positions (given price changes) – or better for this to happen as part of market – update prices?
- Deposit
- Withdraw
- Borrow
- Repay
- Maybe better: Execute Transaction (which can deposit, withdraw, borrow, and repay)


## Liquidator

### Attributes
- ID

### Methods
- Execute Liquidation