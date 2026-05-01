<a name="top"></a>

<div align="center">

<img src="../resources/images/KiCAD-MCP-Server_only_css.svg" alt="KiCAD-MCP-Server Logo" height="240" />

# KiCAD MCP Server

[🇺🇸 **English** (EN)](.github/README.md) &nbsp;•&nbsp; [🇩🇪 **Deutsch** (DE)](#) &nbsp;•&nbsp; [🇨🇳 **中文** (ZH)](.github/README.zh.md)

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](../LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](../docs/PLATFORM_GUIDE.md)
[![KiCAD](https://img.shields.io/badge/KiCAD-9.0+-green.svg)](https://www.kicad.org/)
[![Stars](https://img.shields.io/github/stars/mixelpixx/KiCAD-MCP-Server.svg)](https://github.com/mixelpixx/KiCAD-MCP-Server/stargazers)
[![Discussions](https://img.shields.io/badge/community-Discussions-orange.svg)](https://github.com/mixelpixx/KiCAD-MCP-Server/discussions)

</div>

## <div align="center">

Unser neues Forum ist online: https://forum.orchis.ai — Fragen? Ideen? Projekte zeigen?

</div>

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

4. KI-Client konfigurieren — siehe [Plattform-Anleitung](../docs/PLATFORM_GUIDE.md)

### GitHub Copilot (VS Code)

Template kopieren:

```bash
cp config/vscode-mcp.example.json .vscode/mcp.json
```

VS Code erkennt `.vscode/mcp.json` automatisch und registriert den Server. Das Template nutzt `${workspaceFolder}` — kein Pfad muss angepasst werden.

### Claude Desktop

Konfigurationsdatei bearbeiten:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS/Linux:** `~/.config/claude/claude_desktop_config.json`

Beispielkonfiguration: `config/windows-config.example.json` oder `config/macos-config.example.json`

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
