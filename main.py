```python
from agent import analyze_ticker

def main():
    ticker = "SBER"

    print("Investment Agent MVP")
    print(f"Анализируем: {ticker}")

    result = analyze_ticker(ticker)

    print(result)

if __name__ == "__main__":
    main()
