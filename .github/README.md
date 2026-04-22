<a name="top"></a>

<div align="center">

<img src="../resources/images/KiCAD-MCP-Server_only_css.svg" alt="KiCAD-MCP-Server Logo" height="240" />

# KiCAD MCP Server

[🇺🇸 **English** (EN)](#english) &nbsp;•&nbsp; [🇩🇪 **Deutsch** (DE)](#deutsch) &nbsp;•&nbsp; [🇨🇳 **中文** (ZH)](#中文)

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](../docs/PLATFORM_GUIDE.md)
[![KiCAD](https://img.shields.io/badge/KiCAD-9.0+-green.svg)](https://www.kicad.org/)
[![Stars](https://img.shields.io/github/stars/mixelpixx/KiCAD-MCP-Server.svg)](https://github.com/mixelpixx/KiCAD-MCP-Server/stargazers)
[![Discussions](https://img.shields.io/badge/community-Discussions-orange.svg)](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions)

</div>

<div align="center">
---
Our new forum is up: https://forum.orchis.ai
Need help? Have suggestions? Want to show off your work
---
</div>

## English

**KiCAD MCP Server** is a Model Context Protocol (MCP) server that enables AI assistants like Claude to interact with KiCAD for PCB design automation. Built on the MCP 2025-06-18 specification, this server provides comprehensive tool schemas and real-time project state access for intelligent PCB design workflows.

### Design PCBs with natural language

Describe what you want to build — and let AI handle the EDA work. Place components, create custom symbols and footprints, route connections, run checks, and export production files, all by talking to your AI assistant.

### What it can do today

- Project setup, schematic editing, component placement, routing, DRC/ERC, export
- **Custom symbol and footprint generation** — for modules not in the standard KiCAD library
- **Personal library management** — create once, reuse across projects
- **JLCPCB integration** — parts catalog with pricing and stock data
- **Freerouting integration** — automatic PCB routing via Java/Docker
- **Visual feedback** — snapshots and session logs for traceability
- **Cross-platform** — Windows, Linux, macOS

### Quick Start

1. Install [KiCAD 9.0+](https://www.kicad.org/download/)
2. Install [Node.js 18+](https://nodejs.org/) and [Python 3.11+](https://www.python.org/)
3. Clone and build:

```bash
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
npm install
npm run build
```

4. Configure Claude Desktop — see [Platform Guide](../docs/PLATFORM_GUIDE.md)

### Documentation

- [**Full README**](../README.md) — complete documentation
- [Quick Start (Router Tools)](../docs/ROUTER_QUICK_START.md) — first steps
- [Tool Inventory](../docs/TOOL_INVENTORY.md) — all available tools
- [Schematic Tools Reference](../docs/SCHEMATIC_TOOLS_REFERENCE.md)
- [Routing Tools Reference](../docs/ROUTING_TOOLS_REFERENCE.md)
- [Footprint & Symbol Creator Guide](../docs/FOOTPRINT_SYMBOL_CREATOR_GUIDE.md)
- [JLCPCB Usage Guide](../docs/JLCPCB_USAGE_GUIDE.md)
- [Platform Guide](../docs/PLATFORM_GUIDE.md)
- [Changelog](../CHANGELOG.md)

### Community
- [Forum](https://forum.orchis.ai) — Official Forum for discussions, help, and troubleshooting
- [Discussions](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions) — questions, ideas, showcase
- [Issues](https://github.com/mixelpixx/KiCAD-MCP-Server/issues) — bugs and feature requests
- [Contributing](../CONTRIBUTING.md)

### AI Disclosure

> **Developed with AI Assistance**
> This project was developed with the support of AI-assisted coding tools (GitHub Copilot, Claude).
> All code has been reviewed, tested, and integrated by the maintainers.
> AI tools were used to accelerate development — creative decisions, architecture, and responsibility remain entirely with the authors.

### Disclaimer

> **No Warranty — Use at Your Own Risk**
>
> This project is provided without any warranty, express or implied. The authors and contributors accept no liability for damages of any kind arising from the use or inability to use this software, including but not limited to:
>
> - Errors in generated schematics, PCB layouts, or manufacturing files
> - Damage to hardware, components, or devices caused by incorrect designs
> - Financial losses due to manufacturing errors or incorrect orders
> - Data loss or corruption of KiCAD project files
>
> AI-generated design suggestions do not replace qualified engineering review. Safety-critical applications (medical, aerospace, automotive, etc.) require mandatory independent expert verification.
>
> This project is licensed under the MIT License — which likewise excludes all liability.

<div align="right"><a href="#top"><img src="https://img.shields.io/badge/%E2%96%B4_top-grey?style=flat-square" alt="back to top"></a></div>

---

## Deutsch

**KiCAD MCP Server** ist ein Model Context Protocol (MCP) Server, der KI-Assistenten wie Claude ermöglicht, mit KiCAD für die PCB-Design-Automatisierung zu interagieren. Aufgebaut auf der MCP-Spezifikation 2025-06-18, bietet dieser Server umfassende Tool-Schemas und Echtzeit-Projektzugriff für intelligente PCB-Design-Workflows.

### PCBs mit natürlicher Sprache designen

Beschreibe was du bauen möchtest — und lass die KI die EDA-Arbeit übernehmen. Bauteile platzieren, eigene Symbole und Footprints erstellen, Verbindungen routen, Prüfungen ausführen und Fertigungsdateien exportieren — alles im Gespräch mit deinem KI-Assistenten.

### Was es heute kann

- Projektanlage, Schaltplan-Bearbeitung, Bauteil-Platzierung, Routing, DRC/ERC, Export
- **Eigene Symbole und Footprints generieren** — auch für Module die in KiCAD-Standardbibliotheken fehlen
- **Eigene Bibliotheksverwaltung** — einmal erstellt, in jedem Projekt wiederverwendbar
- **JLCPCB-Integration** — Bauteilkatalog mit Preisen und Lagerbestand
- **Freerouting-Integration** — automatisches PCB-Routing via Java/Docker
- **Visuelles Feedback** — Snapshots und Session-Logs für Nachvollziehbarkeit
- **Plattformübergreifend** — Windows, Linux, macOS

### Schnellstart

1. [KiCAD 9.0+](https://www.kicad.org/download/) installieren
2. [Node.js 18+](https://nodejs.org/) und [Python 3.11+](https://www.python.org/) installieren
3. Klonen und bauen:

```bash
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd KiCAD-MCP-Server
npm install
npm run build
```

4. Claude Desktop konfigurieren — siehe [Plattform-Anleitung](../docs/PLATFORM_GUIDE.md)

### Dokumentation

- [**Vollständige README**](../README.md) — komplette Dokumentation
- [Schnellstart (Router Tools)](../docs/ROUTER_QUICK_START.md) — erste Schritte
- [Werkzeug-Übersicht](../docs/TOOL_INVENTORY.md) — alle verfügbaren Werkzeuge
- [Schaltplan-Werkzeuge](../docs/SCHEMATIC_TOOLS_REFERENCE.md)
- [Routing-Werkzeuge](../docs/ROUTING_TOOLS_REFERENCE.md)
- [Footprint & Symbol erstellen](../docs/FOOTPRINT_SYMBOL_CREATOR_GUIDE.md)
- [JLCPCB-Anleitung](../docs/JLCPCB_USAGE_GUIDE.md)
- [Plattform-Anleitung](../docs/PLATFORM_GUIDE.md)
- [Changelog](../CHANGELOG.md)

### Community

- [Diskussionen](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions) — Fragen, Ideen, Projekte zeigen
- [Issues](https://github.com/mixelpixx/KiCAD-MCP-Server/issues) — Fehler und Feature-Wünsche
- [Mitwirken](../CONTRIBUTING.md)

### KI-Hinweis

> **Entwickelt mit KI-Unterstützung**
> Dieses Projekt wurde unter Einsatz von KI-gestützten Entwicklungswerkzeugen (GitHub Copilot, Claude) erstellt.
> Sämtlicher Code wurde von den Maintainern geprüft, getestet und integriert.
> KI-Werkzeuge dienten der Entwicklungsbeschleunigung — kreative Entscheidungen, Architektur und Verantwortung liegen ausschließlich bei den Autoren.

### Haftungsausschluss

> **Keine Haftung — Nutzung auf eigene Verantwortung**
>
> Dieses Projekt wird ohne jegliche Gewährleistung bereitgestellt — weder ausdrücklich noch stillschweigend. Die Autoren und Mitwirkenden übernehmen keinerlei Haftung für Schäden jeder Art, die durch die Nutzung oder Nichtnutzung dieser Software entstehen, einschließlich aber nicht beschränkt auf:
>
> - Fehler in erzeugten Schaltplänen, PCB-Layouts oder Fertigungsdateien
> - Schäden an Hardware, Bauteilen oder Geräten durch fehlerhafte Designs
> - Finanzielle Verluste durch Fehlproduktionen oder Fehlerbestellungen
> - Datenverlust oder Beschädigung von KiCAD-Projektdateien
>
> KI-generierte Design-Vorschläge ersetzen keine qualifizierte ingenieurtechnische Prüfung. Sicherheitskritische Anwendungen (Medizintechnik, Luftfahrt, Automotive o.ä.) erfordern zwingend eine unabhängige Fachprüfung.
>
> Dieses Projekt steht unter der MIT-Lizenz — die Lizenz schließt ebenfalls jede Haftung aus.

<div align="right"><a href="#top"><img src="https://img.shields.io/badge/%E2%96%B4_top-grey?style=flat-square" alt="back to top"></a></div>

---

## 中文

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

4. 配置 Claude Desktop — 参见 [平台指南](../docs/PLATFORM_GUIDE.md)

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
