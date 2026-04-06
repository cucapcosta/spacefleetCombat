---
sidebar_position: 10
title: Campaign
---

# Campaign System

The campaign is the primary game mode. It wraps the tactical battle system in a strategic layer of territory control, fleet management, economy, and narrative — inspired by BFG Armada 2's campaign map.

## Campaign Structure

### The Sector Map

The campaign takes place across a **sector** of space — a collection of star systems connected by warp routes. Each system contains planets or stations with different strategic value.

```
SECTOR MAP — Koronus Expanse
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  [YOU] Cadia Prime ──── [YOU] Forge Agrippa
         │                      │
         │                      │
  [YOU] Port Maw ────── [???] Bhein Morr
         │                      │
         │                      │
  [   ] Nemesis Tessera── [ENM] Gothic Sector
                                │
                          [ENM] Planet Killer Anchorage

  Legend: [YOU] = Controlled  [ENM] = Enemy  [???] = Contested  [   ] = Neutral
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### System Types

| System Type | Description | Benefit |
|-------------|-------------|---------|
| **Hive World** | Massive population center | High income (+40-60 credits/turn) |
| **Forge World** | Industrial manufacturing hub | Unlocks advanced weapons and upgrades in the shop |
| **Shipyard** | Orbital construction facility | Build new ships. Has construction point capacity. |
| **Outpost** | Minor installation | Small income (+10-20 credits/turn), sensor coverage |
| **Fortress World** | Heavily defended system | Provides defensive bonuses in battles fought here |
| **Warp Gate** | Stable warp route nexus | Fleets can move through for free (no movement cost) |

### System Upgrades

Controlled systems can be upgraded between turns:

| Upgrade | Cost | Effect |
|---------|------|--------|
| **Defense Platform** | 100 | +2 defense turret platforms in battles here |
| **Sensor Array** | 60 | Detect enemy fleet movements 2 systems away |
| **Shipyard Expansion** | 150 | +2 construction points per turn |
| **Trade Route** | 80 | +15 income per turn from this system |
| **Fortifications** | 120 | Defending fleet gets +1 armor on all ships |

## Economy

### Income and Upkeep

Each campaign turn, your treasury changes:

```
treasury_change = total_system_income - fleet_upkeep
```

**System income**: Each controlled system generates credits per turn based on type and upgrades.

**Fleet upkeep**: Each ship costs upkeep per turn:

| Ship Class | Upkeep/Turn |
|------------|-------------|
| Escort | 5 |
| Light Cruiser | 10 |
| Cruiser | 15 |
| Battlecruiser | 20 |
| Battleship | 30 |

**Going bankrupt**: If your treasury drops below 0, you must scuttle ships until upkeep is affordable. Overstretching your fleet is dangerous.

### Ship Building

Ships are built at **shipyards** using construction points:

| Ship Class | Construction Points | Build Time |
|------------|-------------------|------------|
| Escort | 1 | Instant |
| Light Cruiser | 2 | 1 turn |
| Cruiser | 3 | 1 turn |
| Battlecruiser | 4 | 2 turns |
| Battleship | 6 | 2 turns |

- Shipyards regenerate construction points each turn (base: 2/turn, upgradeable)
- Maximum stored construction points depend on shipyard level
- Building a ship costs **credits** (for the hull) plus construction points
- Weapons and upgrades are purchased separately from the ship catalog

### Ship Repairs

Damaged ships require repairs between battles:

- **Minor damage** (above 75% hull): Free, automatic
- **Moderate damage** (50-75% hull): Costs credits, takes 1 turn at a shipyard
- **Heavy damage** (below 50% hull): Costs more credits, takes 2 turns at a shipyard
- **Critical systems damaged**: Additional cost per system repaired
- **Destroyed ships**: Gone permanently. The crew, the upgrades, the experience — all lost.

## Fleet Movement

### Movement Points

Each fleet has **movement points** per campaign turn:

| Fleet Size | Movement Points |
|-----------|----------------|
| 1-3 ships | 3 |
| 4-6 ships | 2 |
| 7+ ships | 1 |

Moving between connected systems costs 1 movement point. Warp Gates cost 0. Commander passive skills can modify movement points.

### Multiple Fleets

You can split your ships into multiple fleets, each moving independently:

```
[Campaign]> split fleet
  Create new fleet from current ships.
  Name: "Vanguard Force"

  > assign vigilant relentless
  ISS Vigilant and ISS Relentless assigned to Vanguard Force.

  Vanguard Force (2 escorts, 70 pts) — at Port Maw
  Main Fleet (ISS Hammer of Light + 2 ships, 930 pts) — at Cadia Prime
```

Fleets in the same system during a battle **combine** for the engagement.

## Urgency System

To prevent turtling and force the campaign forward, an **urgency mechanic** creates time pressure:

- A visible **urgency meter** fills over time (~15-20 turns)
- If it fills completely, you **lose the campaign** (the enemy completes their objective)
- **Completing campaign objectives** resets the urgency meter
- The meter fills faster as the enemy controls more systems
- Narrative justification: the enemy is building toward something catastrophic. You must stop them before it's too late.

```
URGENCY: ████████░░░░░░░░░░░░ (40%)
Estimated turns remaining: 12
Objective: Reclaim Gothic Sector to disrupt enemy supply lines
```

## Campaign Narrative

### Story Missions

The campaign includes scripted **story missions** that advance the narrative:

- Triggered by reaching certain systems or meeting conditions
- Have unique victory conditions (not just "destroy the enemy fleet")
- Award bonus XP, unique commander traits, and special upgrades
- Failing a story mission has narrative consequences but doesn't end the campaign

Example story missions:
- **The Fall of Cadia**: Defend Cadia against overwhelming Chaos assault (survive 15 turns)
- **Convoy Ambush**: Intercept a Chaos supply convoy before it reaches Gothic Sector
- **The Space Hulk**: Board and clear a derelict space hulk — turns into a boarding-focused engagement
- **Duel of Admirals**: Enemy flagship commander challenges you to a flagship duel

### Narrative Events

Between battles, random **narrative events** present choices:

```
==========================================================
  NARRATIVE EVENT — Warp Storm Warning
==========================================================

  Your Navigator reports violent warp currents forming along the
  route to Bhein Morr. The passage is dangerous but still navigable.

  [1] Push through the storm (risk D3 hull damage to each ship,
      but arrive this turn)
  [2] Wait for the storm to pass (safe, but lose 1 campaign turn)
  [3] Route through Nemesis Tessera (safe, costs 2 movement points)

[Event]> 1
  The fleet pushes through the warp storm...
  ISS Hammer of Light takes 2 hull damage from warp turbulence.
  ISS Vigilant navigates safely.
  ISS Relentless takes 1 hull damage.
  Commander Korvus gains trait: "Warp-Touched" (+1 Micro Warp charge, -5 morale)
```

### Commander Death

If your flagship is destroyed in battle and your commander **dies** (small chance, ~10% on flagship destruction):

- The campaign continues with a **new commander** starting at Level 1
- Your fleet remains, but without the commander's abilities and passive skills
- A significant setback, but not campaign-ending
- Narrative flavor: "Vice-Admiral [Name] assumes command of the fleet..."

## Victory and Defeat

### Campaign Victory
- Complete the **final story mission** (varies by campaign)
- Typically involves destroying the enemy's central stronghold or flagship

### Campaign Defeat
- **Urgency meter fills** (enemy completes their objective)
- **All shipyards lost** (cannot build new ships)
- **Commander dies with no ships remaining** (total fleet loss)

### Campaign Score

At the end of a campaign (win or lose), a score is calculated:

| Factor | Points |
|--------|--------|
| Battles won | +50 each |
| Systems controlled at end | +30 each |
| Commander level | +100 per level |
| Ships surviving | +20 per capital ship, +5 per escort |
| Campaign turns taken | -5 per turn (faster = better) |
| Story missions completed | +100 each |

## Campaign Turn Summary

```
CAMPAIGN TURN 14:
  1. Income Phase     — Collect income, pay upkeep
  2. Build Phase      — Purchase ships, weapons, upgrades at shipyards
  3. Repair Phase     — Ships at shipyards are repaired
  4. Movement Phase   — Move fleets along warp routes
  5. Battle Phase     — Resolve any battles (enemy attacks or your assaults)
  6. Event Phase      — Narrative events, story mission triggers
  7. Urgency Phase    — Urgency meter advances
  8. Intel Phase      — Review enemy movements, sensor data
```
