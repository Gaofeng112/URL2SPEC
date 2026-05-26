"""根据 JSON 样本推断简化的 Schema 结构。"""


def infer_type(value):
    """推断单个 Python 值对应的 Schema 类型描述。

    Args:
        value: 任意 Python 对象（通常来自 ``json.loads`` 结果）。

    Returns:
        类型字符串（如 ``"string"``、``"number"``），或嵌套 dict/list 结构。
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if not value:
            return []
        return [infer_schema(value[0])]
    if isinstance(value, dict):
        return infer_schema(value)
    return "unknown"


def infer_schema(data):
    """从 JSON 对象或数组推断简化 Schema。

    对列表仅取首个元素作为元素类型代表；对字典递归推断每个字段。

    Args:
        data: ``dict``、``list`` 或标量值。

    Returns:
        嵌套的 Schema 字典/列表，叶子节点为类型字符串。
    """
    if isinstance(data, dict):
        return {key: infer_type(val) for key, val in data.items()}
    if isinstance(data, list):
        if not data:
            return []
        return [infer_schema(data[0])]
    return infer_type(data)
