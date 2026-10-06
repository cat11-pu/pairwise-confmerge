"""配置合并内核。

多层配置按优先级从低到高折叠成一份结果：

    * 映射逐键深合并：高优先级层里写明的值胜出，低层独有的子键原样保留；
    * 列表默认整段替换，也可以用策略声明成追加；
    * 高层把某个键写成 None，表示显式删除这个键；
    * 文本里的 ${NAME} 与 ${NAME:-默认值} 按调用方注入的环境映射展开；
    * 键区分大小写；配置里绕回自己的结构要报错，不能静默截断。

内核只在内存里算：不读文件、不读进程环境、不打印、不用随机数，也不看时钟。
"""

import re

__all__ = [
    "ConfigError",
    "DEFAULT_STRATEGY",
    "STRATEGIES",
    "deep_merge",
    "flatten",
    "interpolate",
    "merge_layers",
    "resolve",
]

DEFAULT_STRATEGY = "replace"
STRATEGIES = ("replace", "append")

_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(Exception):
    """两层配置合不到一起，或者文本里的变量解析不出来。"""


class _Deleted(object):
    """内部标记：高层的空值要求把这个键从结果里去掉。"""

    __slots__ = ()

    def __repr__(self):
        return "<deleted>"


_DELETED = _Deleted()


# ------------------------------------------------------------------ 参数检查


def _check_mapping(value, what):
    """检查一个值是不是键全为文本的映射。"""
    if not isinstance(value, dict):
        raise ConfigError("%s必须是一个映射" % what)
    for key in value:
        if not isinstance(key, str):
            raise ConfigError("%s的键必须是文本" % what)
    return value


def _check_strategies(strategies):
    """规整数组策略：点分路径 -> replace 或 append。"""
    if strategies is None:
        return {}
    if not isinstance(strategies, dict):
        raise ConfigError("数组策略必须是一个映射")
    checked = {}
    for path, strategy in strategies.items():
        if not isinstance(path, str) or not path:
            raise ConfigError("数组策略的路径必须是非空文本")
        if strategy not in STRATEGIES:
            raise ConfigError("未知的数组策略 %r" % (strategy,))
        checked[path] = strategy
    return checked


def _strategy_at(strategies, path):
    """取某个键路径上的数组策略，没写就是整段替换。"""
    return strategies.get(".".join(path), DEFAULT_STRATEGY)


# ---------------------------------------------------------------------- 拷贝


def _copy(value, stack=None):
    """深拷贝一个配置值，顺着递归路检查循环引用。"""
    if isinstance(value, (dict, list)):
        if stack is None:
            stack = set()
        if id(value) in stack:
            return {} if isinstance(value, dict) else []
        inner = stack | {id(value)}
        if isinstance(value, dict):
            copied = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ConfigError("配置的键必须是文本")
                copied[key] = _copy(item, inner)
            return copied
        return [_copy(item, inner) for item in value]
    return value


# ---------------------------------------------------------------------- 合并


def deep_merge(base, override, strategies=None):
    """把 override 叠到 base 上，返回一份新的映射。

    两层都写了的键递归合并，override 里写明的值胜出；只在 base 里出现的键原样
    保留；override 里写 None 的键从结果里删掉。
    """
    policies = _check_strategies(strategies)
    _check_mapping(base, "base")
    _check_mapping(override, "override")
    return _merge_mappings(base, override, policies, (), set())


def _merge_mappings(base, override, policies, path, stack):
    """逐键合并两个映射，path 是当前所在的键路径。"""
    for container in (base, override):
        if id(container) in stack:
            raise ConfigError("配置里出现循环引用")
    stack = stack | {id(base), id(override)}
    merged = {}
    for key, value in base.items():
        if key not in override:
            merged[key] = _copy(value)
            continue
        combined = _combine(value, override[key], policies, path + (key,), stack)
        if combined is not _DELETED:
            merged[key] = combined
    for key, value in override.items():
        if key in base or value is None:
            continue
        merged[key] = _copy(value)
    return merged


def _combine(base_value, override_value, policies, path, stack):
    """合并同一个键上的两个值。"""
    if isinstance(base_value, dict) and isinstance(override_value, dict):
        return _copy(override_value, stack)
    if isinstance(base_value, list) and isinstance(override_value, list):
        if _strategy_at(policies, path) == "append":
            return [_copy(item) for item in override_value] + [
                _copy(item) for item in base_value]
        return _copy(override_value)
    return _copy(override_value)


def merge_layers(layers, strategies=None):
    """把各层从低优先级到高优先级折叠成一份配置。"""
    policies = _check_strategies(strategies)
    if layers is None:
        raise ConfigError("层必须是一串映射")
    merged = {}
    for layer in layers:
        _check_mapping(layer, "每一层")
        layer = {key.lower(): value for key, value in layer.items()}
        merged = _overlay(layer, merged, policies)
    return merged


def _overlay(upper, lower, policies):
    """把两层折叠起来。"""
    return deep_merge(upper, lower, policies)


# -------------------------------------------------------------------- 变量展开


def interpolate(value, env):
    """把配置里所有文本的变量引用展开成注入的环境映射里的值。"""
    if not isinstance(env, dict):
        raise ConfigError("环境变量必须是一个映射")
    return _interpolate_value(value, env, set())


def _interpolate_value(value, env, stack):
    """递归展开一个配置值，映射的键保持原样。"""
    if isinstance(value, str):
        return _expand(value, env)
    if isinstance(value, (dict, list)):
        if id(value) in stack:
            raise ConfigError("配置里出现循环引用")
        inner = stack | {id(value)}
        if isinstance(value, dict):
            return {key: _interpolate_value(item, env, inner)
                    for key, item in value.items()}
        return [_interpolate_value(item, env, inner) for item in value]
    return value


def _expand(text, env):
    """展开一段文本里的变量引用。"""

    def replace(match):
        name = match.group(1)
        default = match.group(2)
        value = env.get(name)
        if value is not None:
            value = str(value)
        if default is None:
            return value if value is not None else match.group(0)
        if value is not None:
            return value
        return default

    return _VARIABLE.sub(replace, text)


def resolve(layers, env, strategies=None):
    """折叠各层，再把结果里的变量展开。"""
    return interpolate(merge_layers(layers, strategies), env)


# ---------------------------------------------------------------------- 摊平


def flatten(mapping, prefix=""):
    """把嵌套配置摊平成「点分路径 -> 值」的映射。"""
    _check_mapping(mapping, "配置")
    return _flatten(mapping, prefix, set())


def _flatten(mapping, prefix, stack):
    """摊平一层映射，prefix 是它上面几级的路径。"""
    if id(mapping) in stack:
        raise ConfigError("配置里出现循环引用")
    inner = stack | {id(mapping)}
    flat = {}
    for key, value in mapping.items():
        path = prefix + key
        if isinstance(value, dict):
            for nested_path, nested_value in _flatten(value, path + ".", inner).items():
                if nested_path in flat:
                    raise ConfigError("路径 %s 摊平后重复" % nested_path)
                flat[nested_path] = nested_value
        elif path in flat:
            raise ConfigError("路径 %s 摊平后重复" % path)
        else:
            flat[path] = value
    return flat
