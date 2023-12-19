from abc import ABC, abstractproperty
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .comparison_level_creator import ComparisonLevelCreator


class SplinkDialect(ABC):
    # Stores instances of each subclass of SplinkDialect.
    _dialect_instances = {}
    # string defined by subclasses to be used in factory method from_string
    # give a dummy default value so that subclasses that fail to do this
    # don't ruin functionality for existing subclasses
    _dialect_name_for_factory = None

    # Register a subclass of SplinkDialect on its creation.
    # Whenever that subclass is called again, use the previous instance.
    def __new__(cls, *args, **kwargs):
        if cls not in cls._dialect_instances:
            instance = super(SplinkDialect, cls).__new__(cls)
            cls._dialect_instances[cls] = instance
        return cls._dialect_instances[cls]

    @abstractproperty
    def name(self):
        pass

    @property
    def sqlglot_name(self):
        return self.name

    @classmethod
    def from_string(cls, dialect_name: str):
        # list of classes which match _dialect_name_for_factory
        # should just get a single subclass, as this should be unique
        classes_from_dialect_name = [
            c
            for c in cls.__subclasses__()
            if c._dialect_name_for_factory == dialect_name
        ]
        # use sequence unpacking to catch if we duplicate
        # _dialect_name_for_factory in subclasses
        if len(classes_from_dialect_name) == 1:
            subclass = classes_from_dialect_name[0]
            return subclass()
        # error - either too many subclasses found
        if len(classes_from_dialect_name) > 1:
            classes_string = ", ".join(map(str, classes_from_dialect_name))
            error_message = (
                "Found multiple subclasses of `SplinkDialect` with "
                "lookup string `_dialect_name_for_factory` equal to "
                f"supplied value {dialect_name}: {classes_string}!"
            )
        # or _no_ subclasses found
        else:
            error_message = (
                "Could not find subclass of `SplinkDialect` with "
                f"lookup string '{dialect_name}'."
            )
        raise ValueError(error_message)

    @property
    def levenshtein_function_name(self):
        raise NotImplementedError(
            f"Backend '{self.name}' does not have a 'Levenshtein' function"
        )

    @property
    def damerau_levenshtein_function_name(self):
        raise NotImplementedError(
            f"Backend '{self.name}' does not have a 'Damerau-Levenshtein' function"
        )

    @property
    def jaro_winkler_function_name(self):
        raise NotImplementedError(
            f"Backend '{self.name}' does not have a 'Jaro-Winkler' function"
        )

    @property
    def jaro_function_name(self):
        raise NotImplementedError(
            f"Backend '{self.name}' does not have a 'Jaro' function"
        )

    @property
    def jaccard_function_name(self):
        raise NotImplementedError(
            f"Backend '{self.name}' does not have a 'Jaccard' function"
        )

    def try_parse_date(self, name: str, date_format: str = None):
        raise NotImplementedError(
            f"Backend '{self.name}' does not have a 'try_parse_date' function"
        )


class DuckDBDialect(SplinkDialect):
    _dialect_name_for_factory = "duckdb"

    @property
    def name(self):
        return "duckdb"

    @property
    def levenshtein_function_name(self):
        return "levenshtein"

    @property
    def damerau_levenshtein_function_name(self):
        return "damerau_levenshtein"

    @property
    def jaro_function_name(self):
        return "jaro_similarity"

    @property
    def jaro_winkler_function_name(self):
        return "jaro_winkler_similarity"

    @property
    def jaccard_function_name(self):
        return "jaccard"

    @property
    def default_date_format(self):
        return "%Y-%m-%d"

    def try_parse_date(self, name: str, date_format: str = None):
        if date_format is None:
            date_format = self.default_date_format
        return f"""try_strptime({name}, '{date_format}')"""

    # TODO: this is only needed for duckdb < 0.9.0.
    # should we just ditch support for that? (only for cll - engine should still work)
    def array_intersect(self, clc: "ComparisonLevelCreator"):
        clc.col_expression.sql_dialect = self
        col = clc.col_expression
        threshold = clc.min_intersection

        # sum of individual (unique) array sizes, minus the (unique) union
        return (
            f"list_unique({col.name_l}) + list_unique({col.name_r})"
            f" - list_unique(list_concat({col.name_l}, {col.name_r}))"
            f" >= {threshold}"
        ).strip()

class SparkDialect(SplinkDialect):
    _dialect_name_for_factory = "spark"

    @property
    def name(self):
        return "spark"

    @property
    def levenshtein_function_name(self):
        return "levenshtein"

    @property
    def damerau_levenshtein_function_name(self):
        return "damerau_levenshtein"

    @property
    def jaro_function_name(self):
        return "jaro_sim"

    @property
    def jaro_winkler_function_name(self):
        return "jaro_winkler"

    @property
    def jaccard_function_name(self):
        return "jaccard"

    @property
    def default_date_format(self):
        return "yyyy-MM-dd"

    def try_parse_date(self, name: str, date_format: str = None):
        if date_format is None:
            date_format = self.default_date_format
        return f"""to_date({name}, '{date_format}')"""


class SqliteDialect(SplinkDialect):
    _dialect_name_for_factory = "sqlite"

    @property
    def name(self):
        return "sqlite"

    # SQLite does not natively support string distance functions.
    # However, sqlite UDFs are registered automatically by Splink
    @property
    def levenshtein_function_name(self):
        return "levenshtein"

    @property
    def damerau_levenshtein_function_name(self):
        return "damerau_levenshtein"

    @property
    def jaro_function_name(self):
        return "jaro_sim"

    @property
    def jaro_winkler_function_name(self):
        return "jaro_winkler"


class PostgresDialect(SplinkDialect):
    _dialect_name_for_factory = "postgres"

    @property
    def name(self):
        return "postgres"

    @property
    def levenshtein_function_name(self):
        return "levenshtein"

    def date_diff(self, clc: "ComparisonLevelCreator"):
        """Note some of these functions are not native postgres functions and
        instead are UDFs which are automatically registered by Splink
        """

        if clc.date_format is None:
            clc.date_format = "yyyy-MM-dd"

        clc.col_expression.sql_dialect = self
        col = clc.col_expression

        if clc.cast_strings_to_date:
            datediff_args = f"""
                to_date({col.name_l}, '{clc.date_format}'),
                to_date({col.name_r}, '{clc.date_format}')
            """
        else:
            datediff_args = f"{col.name_l}, {col.name_r}"

        if clc.date_metric == "day":
            date_f = f"""
                abs(
                    datediff(
                        {datediff_args}
                    )
                )
            """
        elif clc.date_metric in ["month", "year"]:
            date_f = f"""
                floor(abs(
                    ave_months_between(
                        {datediff_args}
                    )"""
            if clc.date_metric == "year":
                date_f += " / 12))"
            else:
                date_f += "))"
        return f"""
            {date_f} <= {clc.date_threshold}
        """

    def array_intersect(self, clc: "ComparisonLevelCreator"):
        clc.col_expression.sql_dialect = self
        col = clc.col_expression
        threshold = clc.min_intersection
        return f"""
        CARDINALITY(ARRAY_INTERSECT({col.name_l}, {col.name_r})) >= {threshold}
        """.strip()


class AthenaDialect(SplinkDialect):
    _dialect_name_for_factory = "athena"

    @property
    def name(self):
        return "athena"

    @property
    def sqlglot_name(self):
        return "presto"

    @property
    def _levenshtein_name(self):
        return "levenshtein_distance"


_dialect_lookup = {
    "duckdb": DuckDBDialect(),
    "spark": SparkDialect(),
    "sqlite": SqliteDialect(),
    "postgres": PostgresDialect(),
    "athena": AthenaDialect(),
}
