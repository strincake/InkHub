# Windows x64 安装程序与 GitHub Release 自动化方案

## 交付目标与当前状态

目标：普通用户下载 `InkHub-<版本>-windows-x64-setup.exe`，按向导安装后即可启动；不要求安装 Rust、Python、Pillow 或配置开发环境。初次启动自动安装三个内置插件，全部默认禁用。

本方案当前状态：

- **已实现**：Cargo Release 构建自动将三个源码插件打包为 ZIP，并嵌入 EXE；第一次使用带内置插件的版本时安装缺失包，不执行或启用；已有同 ID 包、用户设置和后续卸载选择均保留。
- **尚待实现**：脱离源码路径的资源定位、随包 Python/Pillow、用户数据目录迁移、安装器脚本、
- 打包入口、GitHub Actions 和发布签名。
- **本轮未做**：生成 Setup EXE、上传 Release、公开仓库。本方案中新增文件名和命令均为拟议接口，不是已经存在的工具。

## 推荐方案

采用 **Rust Release + 应用内 Python 运行环境 + Inno Setup + GitHub Actions**。

Inno Setup 可以生成单个安装 EXE，支持快捷方式、升级、卸载和数字签名；使用 `PrivilegesRequired=lowest` 做当前用户安装，不申请管理员权限。商业使用时按官方当前许可要求处理工具授权。

第一阶段只交付 Windows x64。ARM64 与其他系统另建构建矩阵，不把 x64 包标成通用包。

## 安装后的文件与数据

```text
%LOCALAPPDATA%/Programs/InkHub/       应用目录：由安装器升级或卸载
  InkHub.exe                        当前 Rust 宿主，内含三个插件 ZIP
  python/                           worker、插件管理工具与 plugin_kit
  plugins/local-gallery/            旧配置迁移所需的只读模板
  runtime/python/                   固定版本的应用内 CPython + Pillow
  assets/fonts/                     可合法随软件分发的中文字体
  licenses/                         SDK、Python、Pillow、字体等许可声明
  unins000.exe                      安装器生成的卸载入口

%LOCALAPPDATA%/InkHub/               用户目录：升级时保留
  settings.json                     主配置、设备目标和接入密钥
  settings.plugins/                 已安装插件、私有数据和一次性初始化标记
  logs/                             启动与运行错误
```

应用文件与用户可写状态分开。插件 ZIP 是安装源，不代表安装目录中的用户状态；升级不覆盖 `settings.plugins/`。卸载默认保留用户数据，本期不提供隐式清空操作。

## 第一步：完成发布运行时适配

### 资源与解释器定位

1. 安装版通过 `current_exe()` 找到应用目录，所有 worker、安装工具和迁移模板相对该目录定位，替换发布路径中的 `CARGO_MANIFEST_DIR`。
2. 安装版始终启动 `runtime/python/python.exe`，避免依赖 PATH 或调用用户机器上另一套 Python；开发版继续使用当前源码和开发解释器。
3. 默认设置写入用户目录；保留显式 `--config` 能力，测试继续使用隔离配置。
4. 已有源码版用户可显式导入原配置，导入时先备份；安装器不扫描个人目录或自动搬迁未知旧配置。
5. 中文字体从应用内资源加载，不依赖 Windows 字体路径。默认不注册系统字体。

### 双击启动体验

为宿主增加安装版启动参数，例如 `--open-browser`：服务就绪后打开默认浏览器。开始菜单与可选桌面快捷方式使用该入口，不要求执行 PowerShell。发布版隐藏控制台窗口，错误写入用户日志；已有实例时打开同一实例，并避免拉起第二个占用设备的服务。

保持现有网页中的正常退出能力。关闭网页后的进程生命周期在说明中明确；托盘、自启动和在线自动升级不纳入第一版。

### Python 与原生依赖

- 从 Python 官方分发中选择有 Windows x64 embeddable ZIP 的固定版本，记录下载地址和 SHA-256；开发缓存命中后可离线打包。
- 构建机下载与该解释器匹配的 Pillow Windows wheel，校验后放入应用内 `Lib/site-packages`，配置 embeddable Python 的 `_pth` 路径；用户机器不运行 pip，不联网安装依赖。
- 使用应用内解释器实际验证 `import PIL`、图像编码解码、插件 worker 和三个内置插件。
- 检查 EXE/PYD/DLL 的依赖；需要的 Microsoft 运行库按官方分发规则随包处理，或者在验证过的统一静态链接配置下构建。不能仅凭本机可运行就假定干净系统已有依赖。
- 保留 Python、Pillow、SDK、Opus、字体和安装器工具相关的许可声明。

Python 官方 embeddable 包适合应用本地分发；第三方依赖应由应用的构建与安装流程一并供应，不把它当成用户日常管理的系统 Python。

## 第二步：单命令生成安装程序

拟新增的文件：

| 文件 | 职责 |
| --- | --- |
| `packaging/windows/runtime-lock.json` | Python、Pillow wheel、字体等固定版本、官方下载地址、SHA-256 |
| `packaging/windows/InkHub.iss` | Inno Setup 清单：固定 AppId、x64、用户级安装、快捷方式、升级与卸载 |
| `scripts/package-windows.ps1` | 构建、缓存下载、校验、组装、验收、调用 ISCC、生成校验和 |
| `tests/integration/packaged-runtime.py` | 在独立目录及精简环境下验证随包运行能力 |
| `.github/workflows/windows-release.yml` | CI 构建和人工触发的草稿 Release 流程 |

拟议入口：

```powershell
./scripts/package-windows.ps1
```

版本从 `Cargo.toml` 读取，避免 EXE、安装器和 Git 标签版本各自维护。脚本按下列顺序执行，任一阶段失败都停止：

1. 检查工具链与固定版本；版本与标签不一致时拒绝发布。
2. 执行现有 Rust/Python 测试。
3. 执行 `./build.ps1 -Release`，Cargo 自动生成并嵌入内置插件包。
4. 从已校验缓存准备应用内 Python、Pillow 和字体；只复制受控文件清单。
5. 组装 `artifacts/package/windows-x64/<版本>/`，不复制 `target/`、用户设置、日志、真实会话或插件私有数据。
6. 在复制到含空格/中文路径的独立目录中验收：清除开发环境依赖，不依靠源码目录和系统 Python。
7. 用固定版本的 Inno Setup 命令行编译器 `ISCC.exe` 生成 Setup EXE。
8. 若配置了证书，则对宿主、安装器和卸载器签名并加时间戳；未配置则明确标注未签名，不能声称消除 SmartScreen 提示。
9. 输出安装器、同版本便携 ZIP（可选）和 `SHA256SUMS` 到 `dist/releases/`。

安装器应使用稳定 AppId、`ArchitecturesAllowed=x64compatible`、`ArchitecturesInstallIn64BitMode=x64compatible`、`PrivilegesRequired=lowest`，默认安装到当前用户的 Programs 目录。安装前对正在运行的宿主提示正常退出；不得直接结束其他设备应用。

## 第三步：验证安装、升级与卸载

发布门槛：

- 干净 Windows x64 环境中无 Rust/Python/Pillow，断网完成安装并启动模拟屏幕。
- 首次出现三个插件且全部禁用，无设备自动连接，无 Codex 会话扫描或插件执行。
- 分别启用便签、空相册、使用合成会话的工作搭子，验证图片生成、插件主页、禁用和卸载。
- 升级后保留设备配置、API 密钥、相册设置、插件启用状态和用户卸载选择；内置初始化标记不重置。
- 卸载移除应用与快捷方式，保留用户数据。重新安装后仍遵守既有状态。
- 包体扫描无开发机路径依赖、凭据、个人会话、截图和测试状态。

首次自动安装只负责初始化，不是插件自动升级策略；未来升级内置插件需另定版本与数据迁移规则，避免覆盖用户修改。

## 第四步：GitHub Actions 与 Release

建议两个明确入口：

- Pull Request / 手动构建：执行测试、生成安装器并上传 Actions artifact，不创建公开 Release。
- `v<版本>` 标签或手动发布：确认标签与 Cargo 版本一致，复用同一个打包脚本，生成带安装器与校验和的 **Draft Release**，由维护者复核后发布。

构建任务只读仓库；仅 Release 上传任务使用 `contents: write`。Actions 与下载依赖固定版本/校验值。签名证书放 GitHub Secrets，仓库和日志中不保存证书密码。

当前仓库保持私有。有仓库读取权限的用户才能查看 Release；需要面向公众提供下载时，再明确选择将项目改为公开，或另设公开分发仓库。此方案不自动改变仓库可见性。

## 实施顺序

1. 当前已完成内置插件嵌入与默认禁用初始化。
2. 下一轮实现资源定位、应用内 Python、用户目录和双击启动。
3. 实现本机 `package-windows.ps1` 与 `.iss`，生成并实测第一个安装包。
4. 最后接入 Actions、草稿 Release 与可选签名。

这样本机与 CI 使用同一条流水线；安装包成熟后再扩展其他平台。

## 官方依据

- Inno Setup 功能与许可入口：<https://jrsoftware.org/isinfo.php>
- Inno Setup 用户级权限设置：<https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm>
- Python Windows embeddable package：<https://docs.python.org/3.12/using/windows.html#the-embeddable-package>
- GitHub Release 与读取权限：<https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases>
