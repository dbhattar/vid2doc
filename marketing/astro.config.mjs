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