from copy import deepcopy


from .block_from_labels import block_from_labels
from .comparison_vector_values import compute_comparison_vector_values_sql
from .predict import predict_from_comparison_vectors_sqls
from .sql_transform import move_l_r_table_prefix_to_column_suffix
from .blocking import BlockingRule


def labels_table_with_minimal_columns_sql(linker):
    columns_to_select = []
    id_cols = linker._settings_obj._unique_id_input_columns
    for id_col in id_cols:
        columns_to_select.append(f"{id_col.name_l()}")
        columns_to_select.append(f"{id_col.name_r()}")
    columns_to_select.append("clerical_match_score")
    columns_to_select = ", ".join(columns_to_select)

    sql = f"""
    select {columns_to_select}
    from __splink__labels_prepared_for_joining
    """

    return sql


def predict_scores_for_labels_sql(linker):

    brs = linker._settings_obj._blocking_rules_to_generate_predictions
    if brs:
        brs = [move_l_r_table_prefix_to_column_suffix(b.blocking_rule) for b in brs]
        brs = [f"(coalesce({b}, false))" for b in brs]
        brs = " OR ".join(brs)
        br_col = f"({brs})"
    else:
        br_col = " 1=1 "

    id_cols = linker._settings_obj._unique_id_input_columns

    join_conditions = []
    for id_col in id_cols:
        cond = f"pred.{id_col.name_l()} = lab.{id_col.name_l()}"
        join_conditions.append(cond)
        cond = f"pred.{id_col.name_r()} = lab.{id_col.name_r()}"
        join_conditions.append(cond)

    join_conditions = " AND ".join(join_conditions)

    sql = f"""
    select lab.clerical_match_score,
    {br_col} as found_by_blocking_rules,
     pred.*
    from __splink__df_predict as pred
    left join __splink__labels_minimal as lab
    on {join_conditions}

    """

    return sql


def truth_space_table_from_labels_with_predictions_sqls(
    threshold_actual=0.5, match_weight_round_to_nearest=None
):

    # Round to match_weight_round_to_nearest.
    # e.g. if it's 0.25, 1.27 gets rounded to 1.25
    if match_weight_round_to_nearest is not None:
        truth_thres_expr = f"""
            cast({match_weight_round_to_nearest} as float) *
            (round(match_weight/{match_weight_round_to_nearest}))
        """
    else:
        truth_thres_expr = "match_weight"

    # c_P and c_N are clerical positive and negative, respectively
    sqls = []
    sql = f"""
    select
    *,
    {truth_thres_expr} as truth_threshold,
    case when clerical_match_score >= {threshold_actual} then 1
    else 0
    end
    as c_P,
    case when clerical_match_score >= {threshold_actual} then 0
    else 1
    end
    as c_N
    from __splink__labels_with_predictions
    order by match_weight
    """

    sql = {"sql": sql, "output_table_name": "__splink__labels_with_pos_neg"}
    sqls.append(sql)

    sql = """
    select
        truth_threshold,
        count(*) as num_records_in_row,
        sum(c_P) as c_P,
        sum(c_N) as c_N
    from
    __splink__labels_with_pos_neg
    group by truth_threshold
    order by truth_threshold
    """

    sql = {"sql": sql, "output_table_name": "__splink__labels_with_pos_neg_grouped"}
    sqls.append(sql)

    sql = """
    select
    truth_threshold,

    (sum(c_P) over (order by truth_threshold desc))  as cum_clerical_P,
    (sum(c_N) over (order by truth_threshold)) - c_N as cum_clerical_N,

    (select sum(c_P) from __splink__labels_with_pos_neg_grouped) as total_clerical_P,
    (select sum(c_N) from __splink__labels_with_pos_neg_grouped) as total_clerical_N,

    (select sum(num_records_in_row) from __splink__labels_with_pos_neg_grouped)
        as row_count,

    -num_records_in_row + sum(num_records_in_row) over (order by truth_threshold)
        as N_labels,

    sum(num_records_in_row) over (order by truth_threshold desc) as P_labels
    from __splink__labels_with_pos_neg_grouped
    order by  truth_threshold
    """

    sql = {
        "sql": sql,
        "output_table_name": "__splink__labels_with_pos_neg_grouped_with_stats",
    }
    sqls.append(sql)

    sql = """
    select
    truth_threshold,
    row_count,
    total_clerical_P as P,
    total_clerical_N as N,

    P_labels - cum_clerical_P as FP,
    cum_clerical_P as TP,

    N_labels - cum_clerical_N as FN,
    cum_clerical_N as TN

    from __splink__labels_with_pos_neg_grouped_with_stats
    """

    sql = {
        "sql": sql,
        "output_table_name": "__splink__labels_with_pos_neg_grouped_with_truth_stats",
    }
    sqls.append(sql)

    sql = """
    select
    truth_threshold,
    row_count,
    P,
    N,
    TP,
    TN,
    FP,
    FN,
    P/row_count as P_rate,
    cast(N as float)/row_count as N_rate,
    cast(TP as float)/P as TP_rate,
    cast(TN as float)/N as TN_rate,
    cast(FP as float)/N as FP_rate,
    cast(FN as float)/P as FN_rate,
    cast(TP as float)/(TP+FP) as precision,
    cast(TP as float)/(TP+FN) as recall
    from __splink__labels_with_pos_neg_grouped_with_truth_stats
    """

    sql = {"sql": sql, "output_table_name": "__splink__truth_space_table"}
    sqls.append(sql)
    return sqls


def truth_space_table_from_labels_table(
    linker, labels_tablename, threshold_actual=0.5, match_weight_round_to_nearest=None
):

    sqls = predictions_from_sample_of_pairwise_labels_sql(linker, labels_tablename)

    for sql in sqls:
        linker._enqueue_sql(sql["sql"], sql["output_table_name"])

    # Select only necessary columns from labels table
    sql = labels_table_with_minimal_columns_sql(linker)
    linker._enqueue_sql(sql, "__splink__labels_minimal")

    sql = predict_scores_for_labels_sql(linker)
    linker._enqueue_sql(sql, "__splink__labels_with_predictions")

    # c_P and c_N are clerical positive and negative, respectively
    sqls = truth_space_table_from_labels_with_predictions_sqls(
        threshold_actual, match_weight_round_to_nearest
    )

    for sql in sqls:
        linker._enqueue_sql(sql["sql"], sql["output_table_name"])

    df_truth_space_table = linker._execute_sql_pipeline()

    return df_truth_space_table


def truth_space_table_from_labels_column(
    linker, label_colname, threshold_actual=0.5, match_weight_round_to_nearest=None
):

    new_matchkey = len(linker._settings_obj._blocking_rules_to_generate_predictions)

    df_predict = _predict_from_label_column_sql(
        linker,
        label_colname,
    )

    sql = f"""
    select
    cast(({label_colname}_l = {label_colname}_r) as float) as clerical_match_score,
    not (cast(match_key as int) = {new_matchkey})
        as found_by_blocking_rules,
    *
    from {df_predict.physical_name}
    """

    linker._enqueue_sql(sql, "__splink__labels_with_predictions")

    # c_P and c_N are clerical positive and negative, respectively
    sqls = truth_space_table_from_labels_with_predictions_sqls(
        threshold_actual, match_weight_round_to_nearest
    )

    for sql in sqls:
        linker._enqueue_sql(sql["sql"], sql["output_table_name"])

    df_truth_space_table = linker._execute_sql_pipeline()

    return df_truth_space_table


def predictions_from_sample_of_pairwise_labels_sql(linker, labels_tablename):
    sqls = block_from_labels(linker, labels_tablename)

    sql = {
        "sql": compute_comparison_vector_values_sql(linker._settings_obj),
        "output_table_name": "__splink__df_comparison_vectors",
    }

    sqls.append(sql)

    sqls_2 = predict_from_comparison_vectors_sqls(linker._settings_obj)

    sqls.extend(sqls_2)

    return sqls


def prediction_errors_from_labels_table(
    linker,
    labels_tablename,
    include_false_positives=True,
    include_false_negatives=True,
    threshold=0.5,
):
    sqls = predictions_from_sample_of_pairwise_labels_sql(linker, labels_tablename)

    for sql in sqls:
        linker._enqueue_sql(sql["sql"], sql["output_table_name"])

    # Select only necessary columns from labels table
    sql = labels_table_with_minimal_columns_sql(linker)
    linker._enqueue_sql(sql, "__splink__labels_minimal")

    sql = predict_scores_for_labels_sql(linker)
    linker._enqueue_sql(sql, "__splink__labels_with_predictions")

    false_positives = f"""
    (clerical_match_score < {threshold} and
    match_probability > {threshold})
    """

    false_negatives = f"""
    (clerical_match_score > {threshold} and
    match_probability < {threshold})
    """

    where_conditions = []
    if include_false_positives:
        where_conditions.append(false_positives)

    if include_false_negatives:
        where_conditions.append(false_negatives)

    where_condition = " OR ".join(where_conditions)

    sql = f"""
    select *
    from __splink__labels_with_predictions
    where
    {where_condition}
    """

    linker._enqueue_sql(sql, "__splink__labels_with_fp_fn_status")

    return linker._execute_sql_pipeline()


def _predict_from_label_column_sql(linker, label_colname):

    # In the case of labels, we use them to block
    # In the case we have a label column, we want to apply the model's blocking rules
    # but add in blocking on the label colname
    linker = deepcopy(linker)
    settings = linker._settings_obj
    brs = settings._blocking_rules_to_generate_predictions

    label_blocking_rule = BlockingRule(f"l.{label_colname} = r.{label_colname}")
    label_blocking_rule.preceding_rules = brs.copy()
    brs.append(label_blocking_rule)

    # Need the label colname to be in additional columns to retain

    add_cols = settings._additional_columns_to_retain_list

    if label_colname not in add_cols:
        settings._additional_columns_to_retain_list.append(label_colname)

    # Now we want to create predictions
    df_predict = linker.predict()

    return df_predict


def prediction_errors_from_label_column(
    linker,
    label_colname,
    include_false_positives=True,
    include_false_negatives=True,
    threshold=0.5,
):

    df_predict = _predict_from_label_column_sql(
        linker,
        label_colname,
    )

    # Clerical match score is 1 where the label_colname is equal else zero

    # _predict_from_label_column_sql will add a match key for matching on labels
    new_matchkey = len(linker._settings_obj._blocking_rules_to_generate_predictions)

    sql = f"""
    select
    cast(({label_colname}_l = {label_colname}_r) as float) as clerical_match_score,
    not (cast(match_key as int) = {new_matchkey})
        as found_by_blocking_rules,
    *
    from {df_predict.physical_name}
    """

    # found_by_blocking_rules

    linker._enqueue_sql(sql, "__splink__predictions_from_label_column")

    false_positives = f"""
    (clerical_match_score < {threshold} and
    match_probability > {threshold})
    """

    false_negatives = f"""
    ((clerical_match_score > {threshold} and
    match_probability < {threshold})
    or
    (clerical_match_score > {threshold} and
     found_by_blocking_rules = False)
    )
    """

    where_conditions = []
    if include_false_positives:
        where_conditions.append(false_positives)

    if include_false_negatives:
        where_conditions.append(false_negatives)

    where_condition = " OR ".join(where_conditions)

    sql = f"""
    select * from __splink__predictions_from_label_column
    where {where_condition}
    """

    linker._enqueue_sql(sql, "__splink__predictions_from_label_column_fp_fn_only")

    predictions = linker._execute_sql_pipeline()

    return predictions
