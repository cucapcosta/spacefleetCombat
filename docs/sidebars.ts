import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  designSidebar: [
    {
      type: 'category',
      label: 'Game Design',
      items: [
        'design/overview',
        'design/fleet-commander',
        'design/ship-customization',
        'design/ships-and-fleets',
        'design/combat',
        'design/movement',
        'design/stances-and-abilities',
        'design/morale-and-crew',
        'design/detection-and-sensors',
        'design/commands',
        'design/campaign',
        'design/game-modes',
        'design/turn-structure',
      ],
    },
  ],
  architectureSidebar: [
    {
      type: 'category',
      label: 'Architecture',
      items: [
        'architecture/overview',
        'architecture/package-structure',
        'architecture/data-driven-design',
        'architecture/implementation-roadmap',
      ],
    },
  ],
  dataSidebar: [
    {
      type: 'category',
      label: 'Data Reference',
      items: [
        'data/ship-profiles',
        'data/weapon-types',
        'data/upgrade-catalog',
        'data/gunnery-table',
        'data/critical-hits',
      ],
    },
  ],
};

export default sidebars;
