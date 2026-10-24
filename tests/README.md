# 测试目录

所有命令从项目根目录执行。

| 位置 | 职责 |
| --- | --- |
| `lan.rs` | 由 Cargo 自动发现的宿主 Rust 协议测试 |
| `unit/` | 全部 Python 单元测试 |
| `integration/` | 使用宿主、客户端和本机模拟器的八组集成检查 |
| `browser/` | 使用 Playwright 的界面检查 |
| `support/` | 测试专用 NOTE4 回环协议模拟器，不包含旧应用 |
| `archive/` | 已失效的旧界面测试，仅保留历史参考，不纳入现行检查 |
| `manual/` | 针对现有运行实例的手动检查，可能修改该实例的界面状态 |

```powershell
cargo test --locked --workspace
python -m unittest discover -s tests/unit -p "test_*.py"
```

集成与浏览器检查前先完成构建和插件打包；命令及环境要求见[测试说明](../docs/development/testing.md)。测试生成的截图、报告和临时数据统一写入忽略提交的 `artifacts/`，插件包写入 `dist/plugins/`。
