"""confmerge.core 的行为测试。

覆盖多层优先级、深合并、数组替换与追加、显式删除、键大小写、变量展开与
循环引用；只断言调用方能看到的结果，不提示实现怎么写。
"""

import unittest

from confmerge.core import (ConfigError, deep_merge, flatten, interpolate,
                            merge_layers, resolve)


class LayerPriorityTests(unittest.TestCase):
    """多层配置的折叠顺序。"""

    def test_layers_fold_from_low_priority_to_high(self):
        """后给的层优先级更高：同名键取最后一层里写明的值。"""
        layers = [
            {"mode": "dev", "log": {"level": "info", "sinks": ["stdout"]}},
            {"mode": "prod"},
            {"log": {"level": "warn", "sinks": ["file"]}},
        ]
        merged = merge_layers(layers, strategies={"log.sinks": "append"})
        self.assertEqual(merged.get("mode"), "prod")
        self.assertEqual(merged["log"].get("level"), "warn")
        self.assertEqual(merged["log"].get("sinks"), ["stdout", "file"])


class DeepMergeTests(unittest.TestCase):
    """两个映射之间的合并规则。"""

    def test_nested_mappings_are_merged_key_by_key(self):
        """嵌套映射逐键合并：低层独有的子键保留，高层写明的子键覆盖。"""
        merged = deep_merge(
            {"db": {"host": "a", "port": 1, "opts": {"x": 1, "y": 2}}},
            {"db": {"port": 2, "opts": {"y": 3, "z": 4}}})
        self.assertEqual(sorted(merged["db"]), ["host", "opts", "port"])
        self.assertEqual(merged["db"]["host"], "a")
        self.assertEqual(merged["db"]["port"], 2)
        self.assertEqual(merged["db"]["opts"], {"x": 1, "y": 3, "z": 4})

    def test_lists_replace_by_default_and_append_on_request(self):
        """列表默认整段替换；声明为 append 的路径按低层在前、高层在后追加。"""
        base = {"sinks": ["stdout"], "rules": [{"id": 1}]}
        override = {"sinks": ["file"], "rules": [{"id": 2}]}
        replaced = deep_merge(base, override)
        self.assertEqual(replaced["sinks"], ["file"])
        self.assertEqual(replaced["rules"], [{"id": 2}])
        appended = deep_merge(base, override, strategies={"sinks": "append"})
        self.assertEqual(appended["sinks"], ["stdout", "file"])
        self.assertEqual(appended["rules"], [{"id": 2}])
        nested = deep_merge({"a": {"b": [1]}}, {"a": {"b": [2]}},
                            strategies={"a.b": "append"})
        self.assertEqual(nested["a"]["b"], [1, 2])

    def test_a_null_in_a_higher_layer_is_an_explicit_delete(self):
        """高层写 null 表示删掉这个键，同层其它子键不受影响。"""
        merged = deep_merge({"server": {"host": "a", "port": 80, "tls": True}},
                            {"server": {"port": None}})
        self.assertEqual(merged["server"].get("host"), "a")
        self.assertEqual(merged["server"].get("tls"), True)
        self.assertNotIn("port", merged["server"])
        self.assertEqual(deep_merge({"retries": 3}, {"retries": None}), {})
        self.assertEqual(
            merge_layers([{"keep": 1, "drop": 2}, {"drop": None}]), {"keep": 1})

    def test_keys_that_differ_only_in_case_stay_separate(self):
        """键区分大小写：Port 与 port 是两份不同的键。"""
        merged = merge_layers([{"Port": 80, "port": 443, "Host": "a"}])
        self.assertEqual(merged.get("Port"), 80)
        self.assertEqual(merged.get("port"), 443)
        self.assertEqual(merged.get("Host"), "a")
        self.assertEqual(deep_merge({"Path": "/a"}, {"path": "/b"}),
                         {"Path": "/a", "path": "/b"})


class InterpolationTests(unittest.TestCase):
    """注入的环境映射与配置文本之间的展开。"""

    def test_injected_variables_are_expanded_everywhere(self):
        """文本值里的变量展开，列表与映射递归处理，键保持原样。"""
        env = {"HOST": "db.internal", "PORT": "5432", "EMPTY": "", "TAG": "v1"}
        value = {"url": "postgres://${HOST}:${PORT}/app",
                 "note": "${TAG}-${EMPTY}",
                 "list": ["${HOST}", 7, True, None],
                 "plain": "no variables here"}
        self.assertEqual(interpolate(value, env), {
            "url": "postgres://db.internal:5432/app",
            "note": "v1-",
            "list": ["db.internal", 7, True, None],
            "plain": "no variables here",
        })
        self.assertEqual(interpolate({"${HOST}": "${HOST}"}, env),
                         {"${HOST}": "db.internal"})
        self.assertEqual(resolve([{"db": {"host": "${HOST}"}}], env),
                         {"db": {"host": "db.internal"}})

    def test_an_undefined_variable_is_reported(self):
        """没给默认值的未定义变量必须报错，不许把原文留在结果里。"""
        with self.assertRaises(ConfigError):
            interpolate("${MISSING}", {})
        with self.assertRaises(ConfigError):
            resolve([{"db": {"host": "${DB_HOST}"}}], {})
        self.assertEqual(interpolate("${DB_HOST:-localhost}", {}), "localhost")

    def test_a_default_covers_missing_and_empty_variables(self):
        """变量缺失或给成空串时用默认值，给了非空值才用变量。"""
        env = {"EMPTY": "", "SET": "yes"}
        self.assertEqual(interpolate("${MISSING:-fallback}", env), "fallback")
        self.assertEqual(interpolate("${EMPTY:-fallback}", env), "fallback")
        self.assertEqual(interpolate("${SET:-fallback}", env), "yes")
        self.assertEqual(interpolate("${MISSING:-}", env), "")


class GuardTests(unittest.TestCase):
    """循环引用与输入卫生。"""

    def test_a_cyclic_structure_is_reported(self):
        """绕回自己的配置必须报错，共享子结构不算环。"""
        cyclic = {"name": "svc", "limits": {"cpu": 1}}
        cyclic["limits"]["loop"] = cyclic
        self.assertRaises(ConfigError, deep_merge, cyclic, {"name": "other"})
        self.assertRaises(ConfigError, merge_layers, [{"a": 1}, cyclic])
        self.assertRaises(ConfigError, interpolate, cyclic, {})
        self.assertRaises(ConfigError, flatten, cyclic)
        shared = {"x": 1}
        self.assertEqual(deep_merge({"a": shared, "b": shared}, {"c": 2}),
                         {"a": {"x": 1}, "b": {"x": 1}, "c": 2})

    def test_input_hygiene_and_flatten(self):
        """非映射的层、非文本的键、未知策略都要报错，摊平给出点分路径。"""
        self.assertRaises(ConfigError, deep_merge, ["not", "a", "mapping"], {})
        self.assertRaises(ConfigError, merge_layers, [{"ok": 1}, "nope"])
        self.assertRaises(ConfigError, deep_merge, {}, {"a": 1},
                          {"a": "sorted"})
        self.assertRaises(ConfigError, deep_merge, {1: "x"}, {})
        self.assertRaises(ConfigError, interpolate, "${x}", ["not a mapping"])
        self.assertEqual(flatten({"a": {"b": 1}, "c": [1, 2]}),
                         {"a.b": 1, "c": [1, 2]})
        self.assertEqual(merge_layers([]), {})
        self.assertEqual(deep_merge({"a": {"b": 1}}, {"a": {"b": 1}}),
                         {"a": {"b": 1}})


if __name__ == "__main__":
    unittest.main()
