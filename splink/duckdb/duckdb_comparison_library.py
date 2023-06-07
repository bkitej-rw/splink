import warnings

from .comparison_library import *  # noqa: F403

warnings.warn(
    "Importing directly from `splink.duckdb.comparison_library` "
    "is deprecated and will be removed in Splink v4. "
    "Please import from `splink.duckdb.comparison_library` going forward.",
    DeprecationWarning,
    stacklevel=2,
)
