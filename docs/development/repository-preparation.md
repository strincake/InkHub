# 独立项目整理与验证记录

## 目标与范围

将项目整理为可独立构建、便于纳入 Git 的源码目录。原目录保留；不导入本机配置、凭据、插件私有状态和个人会话。本阶段不初始化 Git，不创建或上传 GitHub 仓库。

## 整理计划与结果

- [x] 三个随附插件统一归入 `plugins/`，为便签补齐说明，新增插件索引。
- [x] 宿主 Python worker、安装/迁移工具与 `plugin_kit` API 统一归入 `python/`。
- [x] Python 单元测试归入 `tests/unit/`，集成检查归入 `tests/integration/`，浏览器检查归入 `tests/browser/`。
- [x] 回环模拟器归入 `tests/support/`，会操作现有实例的脚本单独归入 `tests/manual/`。
- [x] 独立打包工具归入 `scripts/`；根目录只保留项目清单、说明、依赖声明和常用 PowerShell 入口。
- [x] 插件包统一输出到 `dist/plugins/`；测试报告、截图及临时数据统一归入 `artifacts/`，加入 Git 忽略。
- [x] 宿主运行路径、旧配置迁移模板路径、打包脚本和全部测试引用同步更新。
- [x] 删除仅转发到多来源相册检查的旧 `gallery-integration.py` 兼容入口，现行入口为 `tests/integration/channels-integration.py`。
- [x] 更新 README、使用/开发指南和客户端依赖路径示例，历史计划及首轮整理记录归档。
- [x] 完成当前布局的集成、浏览器、文档链接与忽略规则复核。

## 依赖边界

设备 SDK 固定在 `vendor/zectrix-local-push-sdk/`，宿主与 HTTP 客户端引用同一份源码快照。来源、Windows 模拟器本地修补、许可证和文件校验记录均保留；本轮没有修改 SDK 或调度算法。

Rust 仅调整了 Python 文件与相册迁移模板的位置；Python 插件 API、网页与三个插件的功能代码保持原实现。历史相册配置兼容迁移继续保留，不因目录整理而移除。

## 当前验证

- `./build.ps1`：新布局的宿主重新编译通过。
- `cargo test --offline --locked --workspace`：26 项通过，0 失败。
- `cargo build --offline --locked --workspace --examples`：客户端示例构建通过。
- `python -m unittest discover -s tests/unit -p "test_*.py"`：49 项通过，0 失败。
- `./pack-plugins.ps1`：三个插件打包通过，产物位于 `dist/plugins/`。
- 八组集成检查：全部通过，覆盖主调度、HTTP/UDP 接入、插件、多来源相册与旧配置迁移、重连、工作搭子、音频及竞争条件。
- 六组现行浏览器检查：`spatial-browser-check.cjs`、`channels-browser-check.cjs`、`companion-browser-check.cjs`、`ui-browser-check.cjs`、`queue-controls-browser-check.cjs`、`source-controls-browser-check.cjs` 全部通过。
- 相册浏览器测试：旧“设备”导航入口改为当前屏幕总览；保存操作改用键盘激活并等待明确的 HTTP 保存响应，继续检查实际持久化字段和通道数量，避免依赖动态 iframe 的瞬时位置或提示文案。
- 历史浏览器基线：旧添加来源界面和单文件夹相册断言已移入 `tests/archive/`，由现行六组检查承担当前功能回归。
- 文档复核：修正过时的插件图片尺寸限制与禁用主页说明，以及工作搭子的启用顺序；现行文档链接无缺失。
- Git 忽略规则：9 个本机或产物路径均被忽略，14 个代表性源码路径均保留；审计使用临时元数据，项目根目录未初始化 Git。
- SDK 快照：原有文件清单与 SHA-256 校验通过，本轮未修改 vendor 内容。

验证使用本机已有 Rust、MSVC、CMake、Python 和 Playwright 环境；这些工具与缓存不作为源码复制。受限环境的 Python 临时目录权限问题通过正常用户权限运行测试处理。

未连接实体 NOTE4，软件模拟测试不代表实际显示、按键或音频效果。本轮完整套件结果见本机 `artifacts/tests/final-summary.json`；报告与截图不纳入源码。初次整理的历史记录在 `docs/archive/repository-preparation-initial.md`，历史本机产物在忽略提交的 `artifacts/history/`。

## 后续阶段

下一步才是初始化 Git、核对首次提交文件和项目许可证、选择远程仓库及公开性，然后连接并上传 GitHub。
