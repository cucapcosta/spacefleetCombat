---
sidebar_position: 11
title: Game Modes
---

# Game Modes

## Campaign (Primary Mode)

The campaign is the **core experience** of Spacefleet Combat. See the [Campaign](campaign) page for full details.

You create a commander, choose a faction, and fight through a series of battles across a sector map. Between battles you manage territory, build ships, customize loadouts, and make narrative choices. Your commander levels up, your ships gain crew experience, and the story unfolds based on your decisions.

### Starting a Campaign

```
==========================================================
  NEW CAMPAIGN
==========================================================

  Choose your faction:
    [1] Imperial Navy — "For the Emperor!"
    [2] Chaos Fleet   — "Death to the False Emperor!"

> 1

  Name your commander: Admiral Korvus

  Choose starting campaign:
    [1] The Gothic War    — Standard difficulty, 12 sectors
    [2] Fall of Cadia     — Hard difficulty, 8 sectors
    [3] Koronus Expanse   — Exploration focus, 16 sectors

> 1

  Your starting fleet:
    ISS Dauntless   (Dauntless Light Cruiser)  — equipped, Green crew
    Cobra Squadron  (3x Cobra Destroyers)      — equipped, Green crew

  Starting system: Cadia Prime (Hive World)
  Treasury: 200 credits

  The Gothic War begins...
```

## Skirmish

A standalone battle for quick play or testing fleet compositions. No campaign progression.

### Setup
1. **Choose points budget** (500 / 1000 / 1500 / 2500)
2. **Select faction** for each side
3. **Build your fleet** using the fleet builder (or pick a preset)
4. **Choose commander level** (determines available abilities and fleet points)
5. **Pick commander abilities and passives** (multiplayer-style: 2 active + 2 passive)
6. **Choose scenario** and AI difficulty

### Scenarios

#### Fleet Engagement
Classic pitched battle. Both fleets deploy on opposite sides and fight until one side is destroyed or routes.

- **Victory**: Destroy or rout 75% of enemy points value
- **Deployment**: Opposing edges of the battlefield
- **Turn Limit**: 20 turns

#### Convoy Raid
One side escorts transports. The other attacks.

- **Defender**: Escort convoy from one edge to the other
- **Attacker**: Destroy the transports (gets more fleet points)
- **Victory**: Defender wins if 50%+ convoy survives

#### Blockade Run
One fleet must break through the other's blockade.

- **Runner**: Starts center, must exit from the blocker's edge
- **Blocker**: Deploys across the middle
- **Victory**: Runner wins if 50%+ fleet value escapes

#### Assassination
Destroy the enemy flagship. Everything else is secondary.

- **Victory**: Destroy the enemy flagship
- **Special**: Flagships start with +2 hull and +1 shield for this scenario
- **Twist**: If both flagships are destroyed on the same turn, it's a draw

## Quick Battle

Jump straight into combat with preset fleets. No building, no customization — just fight.

### Preset Matchups

| Matchup | Description | Size |
|---------|-------------|------|
| **Patrol Clash** | 3 Sword Frigates vs 3 Iconoclast Destroyers | Small |
| **Cruiser Duel** | 1 Lunar Cruiser vs 1 Murder Cruiser | Small |
| **The Torpedo Run** | 4 Cobra Destroyers vs 1 Slaughter Cruiser | Asymmetric |
| **Battle Line** | 2 Cruisers + 4 Escorts vs 2 Cruisers + 4 Escorts | Medium |
| **David vs Goliath** | 6 Cobra Destroyers vs 1 Desolator Battleship | Asymmetric |
| **Fleet Action** | Full 1500-point fleets with all ship types | Large |

Each preset comes with pre-built commander abilities appropriate for the matchup.

## Tutorial

A guided sequence of increasingly complex battles:

1. **First Command**: Move a single ship to waypoints. Learn movement controls.
2. **Weapons Free**: Engage a stationary target. Learn weapon arcs, the gunnery table, and lances.
3. **Under Fire**: Take damage. Learn shields, armor, critical hits, and subsystems.
4. **The Bridge**: Use stances. Learn Lock On, Brace, Reload, and Running Silent.
5. **The Admiral**: Use commander abilities. Learn Emergency Repairs, Call to Arms, Augur Probe.
6. **Fleet Action**: Command 3 ships. Learn fleet coordination, target priority, and morale.
7. **Your Fleet**: Build a fleet from scratch. Learn the fleet builder, weapons, and upgrades.
8. **Campaign Primer**: Play a short 5-turn mini-campaign to learn the strategic layer.

## Multiplayer (Future)

Two human commanders face off in a skirmish-style battle with multiplayer-balanced rules:

### Multiplayer Rules
- **Fixed commander level** (agreed upon, typically 5 or 7)
- **2 active ability slots** + **2 passive skill slots** (chosen, no leveling)
- **Agreed points budget** (typically 1000-1500)
- **No campaign traits** (multiplayer balance — traits are campaign-only)
- **Simultaneous turns** — both players submit orders, then resolution happens
- **Timer** (optional) — per-phase time limit to prevent stalling

### Multiplayer Modes
- **Ranked Skirmish**: Standard fleet engagement with matchmaking
- **Custom Match**: Players agree on all parameters
- **Campaign vs Campaign**: Two players run parallel campaigns that clash when fleets meet (stretch goal)

### Roleplaying in Multiplayer

The CLI nature of the game lends itself to **roleplaying**:
- Players can name their commanders and ships
- Pre-battle and post-battle text exchanges
- Narrative descriptions of combat events encourage storytelling
- Future: integrated chat during battle for in-character communication

```
[Pre-Battle | Admiral Korvus → Admiral Typhus]>
  "Your ragged fleet dares enter Imperial space, heretic?
   The guns of the Hammer of Light will teach you the Emperor's mercy."

[Pre-Battle | Admiral Typhus → Admiral Korvus]>
  "Mercy? The Corpse-Emperor knows nothing of mercy.
   But I shall show you what the Warp teaches about power."
```
