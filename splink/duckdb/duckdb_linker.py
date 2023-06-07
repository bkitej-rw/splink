import warnings

from .linker import DuckDBLinker, DuckDBLinkerDataFrame  # noqa: F401

warnings.warn(
    "Importing directly from `splink.duckdb.duckdb_linker` "
    "is deprecated and will be removed in Splink v4. "
    "Please import from `splink.duckdb.linker` going forward.",
    DeprecationWarning,
    stacklevel=2,
)
