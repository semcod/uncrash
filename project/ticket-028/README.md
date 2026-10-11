# Ticket 028: Testwins UX enhancements for workspace dashboard

- **ID**: ticket-028
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-11

## Goal and scope

Enhance the Uncrash web dashboard user experience (UX) adopting patterns and ergonomics
from `semcod/testwins` (`testwins.ux-strategies/v1`, dashboard pattern):
1. Quick keyboard navigation: `1`..`9` for switching workspaces, `F` for fullscreen, `R` for iframe reload, `Esc` to close preview.
2. Workspace HUD controls: live status pill, tab list indicators, copy noVNC link button with toast feedback, fullscreen toggle.
3. Accessible ergonomics: `:focus-visible` outlines, `@media (prefers-reduced-motion: reduce)`, clear loading and empty states.
4. Automated tests covering the new UX behaviors and keyboard handlers.

## Acceptance criteria

- [x] AC-01: Incorporate Testwins dashboard UX patterns into Uncrash web UI (keyboard shortcuts 1-9 for workspace switching, fullscreen toggle F, reload R, Esc).
- [x] AC-02: Live workspace status indicator (pulse badge, tab pills, copy direct noVNC link button).
- [x] AC-03: Responsive, accessible styling with `:focus-visible`, reduced-motion support, and clean empty/loading states.
- [x] AC-04: Full pytest and governance checks pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
