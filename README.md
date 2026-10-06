# confmerge

一个只依赖 Python 标准库、纯内存的配置合并内核：把多层配置按优先级从低到高折叠成
一份结果，映射逐键深合并、列表按策略替换或追加、高层写空值表示显式删除某个键、
文本里的 `${NAME}` 与 `${NAME:-默认值}` 由调用方注入的映射展开。环境变量不会从进程
里读，内核不看时钟、不起线程，也不做任何 I/O。

- 层：一串普通映射，写在后面的优先级更高；键区分大小写。
- 深合并：两层都写了的键递归合并，高层写明的值胜出，低层独有的子键原样保留。
- 列表：默认整段替换；在策略里把某个键路径声明成 `append` 时按低层在前追加。
- 显式删除：高层把键写成 `None`，这个键从结果里去掉。
- 变量展开：`${NAME}` 取注入映射里的值，`${NAME:-默认值}` 在变量缺失或为空时取默认值。
- 错误：形状不对的输入、未知的数组策略、解析不出来的变量、绕回自己的结构都报
  `ConfigError`，不静默丢键。

## 目录

- `confmerge/core.py`：合并与插值内核
- `tests/test_core.py`：内核的行为测试

## 怎么跑测试

在项目根目录执行：

    python3 -m unittest discover -s tests -v

Windows 上把 `python3` 换成你的解释器路径，例如：

    C:/Users/<你>/AppData/Local/Programs/Python/Python313/python.exe -m unittest discover -s tests -v
