# Ticket 029: Adopt testwins UX patterns for workspace filtering, search, and progressive disclosure

- **ID**: ticket-029
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Adopt UX strategies and patterns from `semcod/testwins` (`testwins.ux-strategies/v1`) for the Uncrash Workspaces Dashboard:
- Add instant search and filter for workspaces with keyword matching across workspace names and tab titles.
- Add provider quick-filter chips (`Wszystkie`, `Codex`, `Antigravity`, `PyCharm`, `Shell`).
- Add empty-state recovery with clear reset action when no workspaces match a filter.
- Add progressive disclosure (`<details><summary>`) for workspace session metadata (display, noVNC port, project directory, terminal tab commands).
- Add keyboard shortcut `/` or `Ctrl+K` to jump to workspace search.
- Ensure full compliance with WCAG 2.2 accessible status messages and reduced motion.

## Acceptance criteria

- [x] AC-01: Workspace search/filter input filters active workspace chips in real time.
- [x] AC-02: Quick filter chips allow filtering workspaces by tool/provider.
- [x] AC-03: An explicit empty state appears when filtering yields no results, offering a reset action.
- [x] AC-04: Progressive disclosure collapsible section displays session metadata without cluttering the preview HUD.
- [x] AC-05: Unit tests verify all new markup, search, filter chips, and metadata disclosure.
- [x] AC-06: `./project/governance-check.sh` passes cleanly.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
