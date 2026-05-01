<a name="top"></a>

<div align="center">

<img src="../resources/images/KiCAD-MCP-Server_only_css.svg" alt="KiCAD-MCP-Server Logo" height="240" />

# KiCAD MCP Server

[🇺🇸 **English** (EN)](README.md) &nbsp;•&nbsp; [🇩🇪 **Deutsch** (DE)](README.de.md) &nbsp;•&nbsp; [🇨🇳 **中文** (ZH)](#)

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](../docs/PLATFORM_GUIDE.md)
[![KiCAD](https://img.shields.io/badge/KiCAD-9.0+-green.svg)](https://www.kicad.org/)
[![Stars](https://img.shields.io/github/stars/mixelpixx/KiCAD-MCP-Server.svg)](https://github.com/mixelpixx/KiCAD-MCP-Server/stargazers)
[![Discussions](https://img.shields.io/badge/community-Discussions-orange.svg)](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions)

</div>

<!-- prettier-ignore-start -->
<div align="center">
---
我们的新论坛已上线：https://forum.orchis.ai — 有问题？有建议？想展示你的作品？
---
</div>
<!-- prettier-ignore-end -->

**KiCAD MCP Server** 是一个模型上下文协议（MCP）服务器，使 Claude 等 AI 助手能够与 KiCAD 交互，实现 PCB 设计自动化。本服务器基于 MCP 2025-06-18 规范构建，为智能 PCB 设计工作流提供全面的工具模式和实时项目状态访问。

### 用自然语言设计 PCB

描述你想构建的内容 — 让 AI 处理 EDA 工作。放置元件、创建自定义符号和封装、布线、运行检查并导出生产文件 — 全程通过与 AI 助手对话完成。

### 当前功能

- 项目创建、原理图编辑、元件放置、布线、DRC/ERC、导出
- **自定义符号和封装生成** — 适用于标准 KiCAD 库中未收录的模块
- **个人库管理** — 一次创建，跨项目复用
- **JLCPCB 集成** — 包含价格和库存数据的元件目录
- **Freerouting 集成** — 通过 Java/Docker 实现自动 PCB 布线
- **可视化反馈** — 快照和会话日志，便于追溯
- **跨平台** — Windows、Linux、macOS

### 快速开始

1. 安装 [KiCAD 9.0+](https://www.kicad.org/download/)
2. 安装 [Node.js 18+](https://nodejs.org/) 和 [Python 3.11+](https://www.python.org/)
3. 克隆并构建：

```bash
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
npm install
npm run build
```

4. 配置 AI 客户端 — 参见 [平台指南](../docs/PLATFORM_GUIDE.md)

### GitHub Copilot（VS Code）

复制配置模板：

```bash
cp config/vscode-mcp.example.json .vscode/mcp.json
```

VS Code 会自动检测 `.vscode/mcp.json` 并注册服务器。模板使用 `${workspaceFolder}`，无需修改路径。

### Claude Desktop

编辑配置文件：

- **Windows：** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS/Linux：** `~/.config/claude/claude_desktop_config.json`

示例配置：`config/windows-config.example.json` 或 `config/macos-config.example.json`

### 文档

- [**完整 README**](../README.md) — 完整文档
- [快速开始（路由工具）](../docs/ROUTER_QUICK_START.md) — 入门指引
- [工具清单](../docs/TOOL_INVENTORY.md) — 所有可用工具
- [原理图工具参考](../docs/SCHEMATIC_TOOLS_REFERENCE.md)
- [布线工具参考](../docs/ROUTING_TOOLS_REFERENCE.md)
- [封装与符号创建指南](../docs/FOOTPRINT_SYMBOL_CREATOR_GUIDE.md)
- [JLCPCB 使用指南](../docs/JLCPCB_USAGE_GUIDE.md)
- [平台指南](../docs/PLATFORM_GUIDE.md)
- [更新日志](../CHANGELOG.md)

### 社区

- [讨论区](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions) — 问题、想法、展示项目
- [问题反馈](https://github.com/mixelpixx/KiCAD-MCP-Server/issues) — 错误报告和功能请求
- [贡献指南](../CONTRIBUTING.md)

### AI 声明

> **借助 AI 辅助开发**
> 本项目在 AI 辅助编码工具（GitHub Copilot、Claude）的支持下开发完成。
> 所有代码均经过维护者的审查、测试和集成。
> AI 工具用于加速开发 — 创意决策、架构设计和责任归属完全由作者承担。

### 免责声明

> **不提供任何保证 — 使用风险自负**
>
> 本项目按现状提供，不附带任何明示或暗示的保证。作者和贡献者对因使用或无法使用本软件而造成的任何类型的损害不承担任何责任，包括但不限于：
>
> - 生成的原理图、PCB 布局或生产文件中的错误
> - 因设计错误导致的硬件、元件或设备损坏
> - 因生产错误或错误订单造成的经济损失
> - KiCAD 项目文件的数据丢失或损坏
>
> AI 生成的设计建议不能替代专业工程师审查。安全关键型应用（医疗、航空航天、汽车等）必须进行独立的专业验证。
>
> 本项目采用 MIT 许可证 — 该许可证同样排除一切责任。

<div align="right"><a href="#top"><img src="https://img.shields.io/badge/%E2%96%B4_top-grey?style=flat-square" alt="back to top"></a></div>
