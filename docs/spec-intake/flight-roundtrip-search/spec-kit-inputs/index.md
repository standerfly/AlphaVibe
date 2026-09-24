# Spec Kit Inputs Index: 機票查詢：四段票天數區間化＋單純來回搜尋

**Feature Slug:** flight-roundtrip-search
**Last Updated:** 2026-09-24

| Spec Feature Slug | Status | Scope Summary | Dependencies | Source Decisions | Handoff Order |
|--------------------|--------|-----------------|-----------------|---------------------|-----------------|
| trip-day-range | Draft | 既有四段票 `trip_days` 從單一整數升級為區間；schema 遷移、枚舉邏輯、前端表單、id=9 遷移並重新查價、組合數上限守衛 | 無（前提工作） | Q-005、Q-006、Q-007、Q-009、Q-010 | 1 |
| roundtrip-search | Draft | 新增「單純來回」查詢類型：多目的地候選、區間天數、可選轉機城市偏好、整合同一機票分頁類型切換、通知標示觸發目的地 | 依賴 trip-day-range | Q-001、Q-002、Q-003、Q-004、Q-008、Q-009、Q-010 | 2 |
