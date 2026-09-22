# Changelog

All notable changes to the Knowledge Agent Desktop project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-22

### Added

- Initial release of Knowledge Agent Desktop
- Electron-based desktop application with Vue 3 frontend
- Custom title bar with window controls (minimize, maximize, close)
- System tray integration with context menu
- Backend connection status monitoring
- IPC communication between main and renderer processes
- Cross-platform support (Windows, macOS, Linux)
- Auto-updater infrastructure
- File dialog integration (open/save)
- Clipboard operations
- System notifications
- Responsive desktop layout
- All existing web features:
  - Multi-agent chat with SSE streaming
  - Blog management with Markdown editor
  - Knowledge base with document upload and search
  - MCP tools management
  - Observability dashboard
  - Security and approval workflows

### Technical

- Electron 28 with electron-vite
- Vue 3.5 with Composition API
- Element Plus 2.8 UI components
- Pinia 2.2 state management
- Vue Router 4.4 with lazy loading
- TypeScript 5.6 support
- Vite 5.4 build tooling
- electron-builder for packaging

## [Unreleased]

### Planned

- Local backend bundling
- Offline mode support
- Window state persistence
- Global keyboard shortcuts
- Native menus
- Code signing
- Performance optimizations
