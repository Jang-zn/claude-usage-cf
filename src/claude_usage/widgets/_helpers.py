"""Shared helper functions for widgets."""


def format_tokens(n: int) -> str:
    """Format token count: 32100000 -> '32.1M', 5200 -> '5.2K'"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def make_bar(
    filled_ratio: float,
    width: int = 30,
    fill_char: str = "█",
    empty_char: str = "░",
) -> str:
    """Create a horizontal bar."""
    filled = int(filled_ratio * width)
    return fill_char * filled + empty_char * (width - filled)
