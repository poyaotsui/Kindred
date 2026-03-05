# Stock Trading Simulator

A Python-based stock trading simulator with a modern GUI interface that allows users to practice trading stocks with virtual money.

## Features

- Real-time stock price updates using Yahoo Finance API
- Interactive price charts
- Portfolio management
- Transaction history
- Buy and sell functionality
- Starting balance of $10,000

## Requirements

- Python 3.x
- PyQt6
- yfinance
- pandas
- matplotlib

## Installation

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## How to Use

1. Run the simulator:
```bash
python stock_simulator.py
```

2. Using the simulator:
- Enter a stock symbol (e.g., AAPL, GOOGL, MSFT) in the input field
- View the current price and 30-day price history chart
- Enter the quantity of shares you want to buy/sell
- Click Buy or Sell to execute trades
- Monitor your portfolio and transaction history in their respective tabs

## Notes

- This is a simulator using real stock data but with virtual money
- Stock prices are updated every 5 seconds
- The simulator uses the Yahoo Finance API to fetch real-time stock data 