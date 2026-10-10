# Ticket 007: Preview windows and terminal tabs before snapshot restore with noVNC

- **ID**: ticket-007
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-10

## Goal and scope

Add ability to preview recorded windows, GUI applications, and terminal tabs from a selected snapshot before restoration, supporting isolated noVNC/virtual desktop preview and launching recorded terminal tabs in the system terminal.

## Acceptance criteria

- [x] AC-01: Extract recorded terminal tabs and window provenance from snapshot manifests (`session_hosts`, `jetbrains_live_state`).
- [x] AC-02: Implement preview API and CLI command `uncrash preview [SNAPSHOT]` providing structured summary of windows, tabs, and restored paths.
- [x] AC-03: Support isolated graphical preview on a private virtual display with noVNC (`--novnc`, `--port`, `--screenshot`) using TigerVNC/websockify when available.
- [x] AC-04: Support generating and launching recorded terminal tabs in the system terminal (`gnome-terminal` / bash).
- [x] AC-05: Unit and regression test suite verifying preview extraction, command line interface, and graceful degradation when display tools are absent.
- [x] AC-06: Web client served via `uncrash serve --port <PORT>` providing interactive dashboard to graphically inspect snapshots, recorded terminal tabs, launch noVNC preview or system terminal tabs.
- [x] AC-07: Managed governance check passes cleanly with 0 errors.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
