import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://raven.ai',
  integrations: [
    starlight({
      title: 'RAVEN Documentation',
      customCss: [],
      sidebar: [
        {
          label: 'Overview',
          items: [
            { label: 'System Architecture', link: '/01-system-architecture/' },
            { label: 'Platform Connectors', link: '/02-platform-connectors/' },
            { label: 'Voice & Personality', link: '/03-voice-personality/' },
            { label: 'Tools Ecosystem', link: '/04-tools-ecosystem/' },
            { label: 'Sensor Awareness', link: '/05-sensor-awareness/' },
            { label: 'Safety & Moderation', link: '/06-safety-moderation/' },
            { label: 'ML Depth', link: '/07-ml-depth/' },
          ],
        },
        {
          label: 'Development & Deployment',
          items: [
            { label: 'Deployment & Scaling', link: '/08-deployment-scaling/' },
            { label: 'Repository Structure', link: '/09-repository-structure/' },
            { label: 'PicoClaw Integration', link: '/10-picoclaw-integration-low-cost-iot-distributed-ai/' },
            { label: 'ZeroClaw Study Report', link: '/11-zeroclaw-study-report/' },
            { label: 'Modular Platform Integration', link: '/12-modular-platform-integration/' },
            { label: 'Gap Analysis', link: '/13-jarvis-friday-gap-analysis-2026-06/' },
          ],
        }
      ],
    }),
  ],
});
