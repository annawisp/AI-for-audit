# Capabilities

每个审计能力应当：

1. 有明确、可验证的输入契约；
2. 输出统一 Evidence Object 或可转换结果；
3. 可以独立运行、测试、停用；
4. 对缺失输入执行局部降级，不伪造结论；
5. 在本目录下使用独立子目录，并包含 `inputs.py`、`outputs.py`、`service.py` 与对应测试。

具体能力从 TASK-301 开始实现。

