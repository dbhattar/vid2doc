// @ts-check
import { defineConfig } from 'astro/config';

import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';

import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
  site: 'https://framewrite.cc',
  integrations: [
    starlight({
      title: 'Framewrite Docs',
      description: 'API reference for the Framewrite conversion API.',
      customCss: ['./src/styles/tokens.css', './src/styles/starlight-overrides.css'],
      // Starlight renders /docs/* through its own page shell, not BaseLayout.astro, so
      // the GA4 tag needs to be injected here too -- otherwise docs traffic goes untracked.
      head: [
        {
          tag: 'script',
          attrs: { async: true, src: 'https://www.googletagmanager.com/gtag/js?id=G-RTNCYF5ZX0' },
        },
        {
          tag: 'script',
          content: `window.dataLayer = window.dataLayer || [];
function gtag(){dataLayer.push(arguments);}
gtag('js', new Date());
gtag('config', 'G-RTNCYF5ZX0');`,
        },
      ],
      sidebar: [
        {
          label: 'API Reference',
          items: [
            { label: 'Getting Started', slug: 'docs/getting-started' },
            { label: 'Authentication', slug: 'docs/authentication' },
            { label: 'Submit a Job', slug: 'docs/submit-a-job' },
            { label: 'Check Status & Get Results', slug: 'docs/check-status-and-results' },
          ],
        },
      ],
    }),
    mdx(),
    sitemap(),
  ],
});