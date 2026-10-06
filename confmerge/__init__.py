"""confmerge：多层配置合并与变量插值内核。

对外入口：
    ConfigError      层合不到一起，或者文本里的变量解析不出来
    deep_merge       两个映射的深合并
    merge_layers     多层配置按优先级从低到高折叠
    interpolate      按调用方注入的映射展开配置文本里的变量
    resolve          折叠各层之后再展开变量
    flatten          把嵌套配置摊平成点分路径
"""

from .core import (ConfigError, DEFAULT_STRATEGY, STRATEGIES, deep_merge,
                   flatten, interpolate, merge_layers, resolve)

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
