import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header style={{
      padding: '4rem 0',
      textAlign: 'center',
      backgroundColor: 'var(--ifm-color-primary-darkest)',
      color: 'white',
    }}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle" style={{fontSize: '1.4rem', opacity: 0.9}}>
          {siteConfig.tagline}
        </p>
        <div style={{display: 'flex', gap: '1rem', justifyContent: 'center', marginTop: '2rem'}}>
          <Link
            className="button button--secondary button--lg"
            to="/design/overview">
            Game Design
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/architecture/overview">
            Architecture
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/data/ship-profiles">
            Ship Data
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={siteConfig.title}
      description="CLI tactical spaceship combat game documentation">
      <HomepageHeader />
      <main style={{padding: '2rem', maxWidth: '800px', margin: '0 auto'}}>
        <pre style={{
          backgroundColor: 'var(--ifm-code-background)',
          padding: '1.5rem',
          borderRadius: '8px',
          fontSize: '0.85rem',
          lineHeight: '1.5',
          overflow: 'auto',
        }}>
{`==========================================================
  TURN 3 - SHOOTING PHASE
==========================================================

[Turn 3 | SHOOTING | ISS Hammer of Light]> fire broadside port at defiler

  Port Weapons Battery (str 6): Target IN arc, range OK.
    LOCK ON active: column shift right.
    Gunnery table: str 6, running column -> 3 hits!
    Defiler shields absorb 1 hit.
    Armor saves vs 2 remaining: [3, 6] -> 1 penetrates!
    1 hull damage -> Defiler now at 7/10 hull.
    Critical hit check: 2D6 = 9 -> FIRE! Decks ablaze!

[Turn 3 | SHOOTING | ISS Hammer of Light]> scan defiler

  TARGET SCAN - "Defiler" (Murder-class Cruiser)
  Hull:    7/10 [#######...]
  Shields: 0/2  [..]
  Status:  FIRE (ongoing)
  Bearing: 280  Range: 38 GU  Heading: 200

[Turn 3 | SHOOTING | ISS Hammer of Light]> _`}
        </pre>
      </main>
    </Layout>
  );
}
