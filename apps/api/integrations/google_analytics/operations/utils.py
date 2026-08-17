# apps/api/integrations/google_analytics/operations/utils.py

"""Google Analytics report request compilers."""

from typing import Any

from ..tools.schemas import GoogleAnalyticsFieldFilter, GoogleAnalyticsOrderBy


def compile_filter_expression(
    filters: list[GoogleAnalyticsFieldFilter] | None,
) -> dict[str, Any] | None:
    if not filters:
        return None
    expressions = [_compile_filter(item) for item in filters]
    if len(expressions) == 1:
        return expressions[0]
    return {"andGroup": {"expressions": expressions}}


def compile_order_bys(order_bys: list[GoogleAnalyticsOrderBy] | None) -> list[dict[str, Any]]:
    compiled: list[dict[str, Any]] = []
    for item in order_bys or []:
        value: dict[str, Any] = {"desc": item.desc}
        if item.metric is not None:
            value["metric"] = {"metricName": item.metric}
        else:
            dimension = {"dimensionName": item.dimension}
            if item.order_type is not None:
                dimension["orderType"] = item.order_type
            value["dimension"] = dimension
        compiled.append(value)
    return compiled


def _compile_filter(item: GoogleAnalyticsFieldFilter) -> dict[str, Any]:
    filter_value: dict[str, Any] = {"fieldName": item.field_name}
    if item.string_filter is not None:
        filter_value["stringFilter"] = {
            "matchType": item.string_filter.match_type,
            "value": item.string_filter.value,
            "caseSensitive": item.string_filter.case_sensitive,
        }
    elif item.in_list_filter is not None:
        filter_value["inListFilter"] = {
            "values": item.in_list_filter.values,
            "caseSensitive": item.in_list_filter.case_sensitive,
        }
    elif item.numeric_filter is not None:
        filter_value["numericFilter"] = {
            "operation": item.numeric_filter.operation,
            "value": _numeric_value(item.numeric_filter.value),
        }
    else:
        between_filter = item.between_filter
        if between_filter is None:
            raise ValueError("Google Analytics field filter has no leaf filter")
        filter_value["betweenFilter"] = {
            "fromValue": _numeric_value(between_filter.from_value),
            "toValue": _numeric_value(between_filter.to_value),
        }
    expression = {"filter": filter_value}
    return {"notExpression": expression} if item.negate else expression


def _numeric_value(value: float) -> dict[str, float | str]:
    if value.is_integer():
        return {"int64Value": str(int(value))}
    return {"doubleValue": value}
