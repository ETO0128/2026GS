"""Compatibility entry point for producing the official Question 4-2 workbook.

The implementation is intentionally shared with ``run_q4_2`` so the workbook,
summary, figure and paper cannot silently use different forecasting models.
"""
from run_q4_2 import main


if __name__ == "__main__":
    main()
