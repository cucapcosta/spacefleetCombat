---
sidebar_position: 3
title: Gunnery Table
---

# Gunnery Table Reference

The gunnery table determines how many hits a **weapon battery** scores based on its firepower and the engagement conditions.

## Reading the Table

1. Start with the weapon's **strength** (firepower dice) → this is the row
2. Determine the **column** based on target aspect and modifiers
3. Cross-reference to find the number of hits

## Column Determination

### Base Column: Target Aspect
How is the target oriented relative to the line of fire?

| Target Aspect | Column | Description |
|--------------|--------|-------------|
| **Closing** | Closing (-1) | Target's prow is facing toward you (small profile) |
| **Abeam** | Abeam (0) | Target's broadside is exposed (standard) |
| **Running** | Running (+1) | Target's stern is facing you (easy target) |

### Column Shifts
| Modifier | Shift |
|----------|-------|
| Lock On special order | +1 (right) |
| Long range (>50% of max) | Halve firepower instead |

### Minimum/Maximum Columns
- Cannot shift below **Far Closing** (-2)
- Cannot shift above **Far Running** (+2)

## The Table

| Firepower | Far Closing | Closing | Abeam | Running | Far Running |
|-----------|-------------|---------|-------|---------|-------------|
| **1** | 0 | 0 | 1 | 1 | 1 |
| **2** | 0 | 1 | 1 | 1 | 2 |
| **3** | 0 | 1 | 1 | 2 | 2 |
| **4** | 1 | 1 | 2 | 2 | 3 |
| **5** | 1 | 1 | 2 | 3 | 3 |
| **6** | 1 | 2 | 2 | 3 | 4 |
| **7** | 1 | 2 | 3 | 3 | 4 |
| **8** | 1 | 2 | 3 | 4 | 5 |
| **9** | 2 | 2 | 3 | 4 | 5 |
| **10** | 2 | 3 | 4 | 4 | 6 |
| **11** | 2 | 3 | 4 | 5 | 6 |
| **12** | 2 | 3 | 4 | 5 | 7 |
| **13** | 3 | 3 | 5 | 6 | 7 |
| **14** | 3 | 4 | 5 | 6 | 8 |
| **15** | 3 | 4 | 5 | 7 | 8 |
| **16** | 3 | 4 | 6 | 7 | 9 |

For firepower above 16, split into multiple attacks.

## Example Resolutions

### Example 1: Standard Broadside
- Lunar Cruiser fires Port Weapons Battery (str 6) at an enemy showing its broadside
- Column: **Abeam** (target broadside exposed)
- Table lookup: str 6, Abeam → **2 hits**

### Example 2: Lock On Broadside
- Same situation, but the Lunar Cruiser has Lock On orders
- Column: Abeam + Lock On shift right → **Running**
- Table lookup: str 6, Running → **3 hits**

### Example 3: Long Range vs Closing Target
- Emperor Battleship fires Port Battery (str 8) at range 40 GU (max 60)
- Range is >50% of max → firepower halved to 4
- Target is closing (showing prow) → column: **Closing**
- Table lookup: str 4, Closing → **1 hit**

### Example 4: Close Range vs Running Target with Lock On
- str 6, target running, Lock On active
- Column: Running + Lock On → **Far Running**
- Table lookup: str 6, Far Running → **4 hits**
- This is the best-case scenario for batteries!
