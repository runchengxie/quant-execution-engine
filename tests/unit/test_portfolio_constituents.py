from pathlib import Path

import pandas as pd
import pytest  # Import the pytest library

pytestmark = pytest.mark.integration

# --- Path Configuration ---
try:
    # This block determines the project root directory from the current file's location.
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
except NameError:
    # This is a fallback for interactive environments (like notebooks)
    # where __file__ is not defined.
    PROJECT_ROOT = (
        Path(".").resolve().parent
        if "tests" in str(Path(".").resolve())
        else Path(".").resolve()
    )

DATA_DIR = PROJECT_ROOT / "data"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PORTFOLIO_FILE = OUTPUTS_DIR / "point_in_time_backtest_quarterly_sp500_historical.xlsx"
CONSTITUENTS_FILE = DATA_DIR / "sp500_historical_constituents.csv"


# --- Pytest Fixtures: Prepare data needed for tests ---


@pytest.fixture(
    scope="session"
)  # scope="session" means this fixture runs only once per test session
def sp500_constituents() -> pd.DataFrame:
    """
    Loads the S&P 500 historical constituents data as a reusable test resource.
    """
    if not CONSTITUENTS_FILE.exists():
        pytest.skip(f"Ground truth file not found, skipping tests: {CONSTITUENTS_FILE}")

    df = pd.read_csv(CONSTITUENTS_FILE)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(
        df["end_date"], errors="coerce"
    )  # 'coerce' turns invalid dates into NaT
    df["ticker"] = df["ticker"].str.upper().str.strip()
    return df


@pytest.fixture(scope="session")
def portfolio_excel_file() -> pd.ExcelFile:
    """
    Loads the portfolio Excel file as a reusable test resource.
    """
    if not PORTFOLIO_FILE.exists():
        pytest.skip(f"Portfolio file not found, skipping tests: {PORTFOLIO_FILE}")

    return pd.ExcelFile(PORTFOLIO_FILE)


# --- Parametrization: Dynamically generate test cases ---


def get_portfolio_sheet_names():
    """
    Helper function to read the list of sheet names from the Excel file for
    parametrization.
    """
    if not PORTFOLIO_FILE.exists():
        return []
    xls = pd.ExcelFile(PORTFOLIO_FILE)
    return xls.sheet_names


# --- Core Test Logic ---


def verify_membership(
    portfolio_date: pd.Timestamp, portfolio_tickers: list, df_constituents: pd.DataFrame
) -> list:
    """
    (Helper function) Verifies if a given list of tickers were members of the
    S&P 500 on a specific date.
    Returns a list of tickers that were not members.
    """
    misfit_tickers = []
    check_date = (
        portfolio_date.normalize()
    )  # Normalize to midnight for consistent date comparison

    for ticker in portfolio_tickers:
        ticker_history = df_constituents[df_constituents["ticker"] == ticker]
        if ticker_history.empty:
            misfit_tickers.append(ticker)
            continue

        # A stock is a member if the check_date is between its start_date (inclusive)
        # and end_date (exclusive), or if the end_date is not set (NaT).
        is_member = (
            (ticker_history["start_date"] <= check_date)
            & (
                pd.isna(ticker_history["end_date"])
                | (ticker_history["end_date"] > check_date)
            )
        ).any()

        if not is_member:
            misfit_tickers.append(ticker)

    return misfit_tickers


# --- Pytest Test Functions ---


@pytest.mark.parametrize("sheet_name", get_portfolio_sheet_names())
def test_portfolio_stocks_are_valid_sp500_members(
    sheet_name: str,
    portfolio_excel_file: pd.ExcelFile,
    sp500_constituents: pd.DataFrame,
):
    """
    This is a parameterized test.
    It runs independently for each sheet (sheet_name) in the Excel file.
    It verifies that all stocks in the sheet's portfolio were valid S&P 500
    members on the corresponding date.
    """
    # 1. Prepare data from test parameters and fixtures
    portfolio_date = pd.to_datetime(sheet_name)
    df_portfolio = portfolio_excel_file.parse(sheet_name)
    tickers_to_check = df_portfolio["Ticker"].tolist()

    if not tickers_to_check:
        pytest.skip(f"Portfolio is empty for this date: {sheet_name}")

    # 2. Execute the core verification logic
    misfit_tickers = verify_membership(
        portfolio_date, tickers_to_check, sp500_constituents
    )

    # 3. Use assert to declare the expected outcome
    # The assertion fails if misfit_tickers is not empty, and pytest will report
    # the error.
    assert not misfit_tickers, (
        f"On {portfolio_date.date()}, found tickers that were not S&P 500 members: "
        f"{misfit_tickers}"
    )
