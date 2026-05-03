# docs/

Project documentation for eBay Workstation Hunter.

---

## spec.md — Build Specification

The original technical specification for the tool. Covers the full scope:
target hardware (Threadripper PRO 5000-series workstations on WRX80 platforms),
the eBay Browse API integration, search query strategy, PSU classification,
the 100-point scoring model, pricing tiers, persistence and change detection,
terminal output format, and CLI interface. Also includes production verification
notes appended after initial API testing.

This document is the authoritative reference for scoring weights, discard
rules, and data structures. If the code and spec disagree, the spec wins.

---

## session-instructions.md — Clarifying Prompt

A companion document to the spec that defined the build workflow for the
initial Claude Code session. Covers the GitHub repository setup, the
incremental build order (auth → search → dedup → filters → scoring →
persistence → output → CLI → watch mode), sandbox and production test
sequences, and the PR/merge process. Also defines when to stop and ask
versus proceed autonomously.
