// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	integrations: [
		starlight({
			title: 'RAVEN Documentation',
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/swadhin/SARAS' }],
			sidebar: [
				{
					label: 'Overview',
					items: [
						{ label: 'Overview', slug: '00-overview' },
						{ label: 'System Architecture', slug: '01-system-architecture' },
						{ label: 'Installation', slug: 'installation' },
						{ label: 'Status (2026-06)', slug: 'status_2026_06' },
						{ label: 'Gap Analysis', slug: 'gap_analysis_2026_06' },
					],
				},
				{
					label: 'Core Components',
					items: [
						{ label: 'Platform Connectors', slug: '02-platform-connectors' },
						{ label: 'Voice & Personality', slug: '03-voice-personality' },
						{ label: 'Tools Ecosystem', slug: '04-tools-ecosystem' },
						{ label: 'Sensor Awareness', slug: '05-sensor-awareness' },
						{ label: 'Safety & Moderation', slug: '06-safety-moderation' },
						{ label: 'ML Depth', slug: '07-ml-depth' },
					],
				},
				{
					label: 'Deployment & Hardware',
					items: [
						{ label: 'Deployment & Scaling', slug: '08-deployment-scaling' },
						{ label: 'Repository Structure', slug: '09-repository-structure' },
						{ label: 'PicoClaw Integration', slug: '10-picoclaw-integration-low-cost-iot-distributed-ai' },
						{ label: 'ZeroClaw Study Report', slug: '11-zeroclaw-study-report' },
						{ label: 'Modular Platform Integration', slug: '12-modular-platform-integration' },
					],
				},
				{
					label: 'Features',
					items: [
						{ label: 'Core', slug: 'features-core' },
						{ label: 'Voice', slug: 'features-voice' },
						{ label: 'Tool Gateway', slug: 'features-tool-gateway' },
						{ label: 'Skills', slug: 'features-skills' },
						{ label: 'Sensors', slug: 'features-sensors' },
						{ label: 'Safety', slug: 'features-safety' },
						{ label: 'Media & Web', slug: 'features-media-web' },
						{ label: 'Automation', slug: 'features-automation' },
					]
				},
				{
					label: 'Guides',
					items: [
						{ label: 'Agents', slug: 'guides-agents' },
						{ label: 'SOUL', slug: 'guides-soul' },
						{ label: 'Tutorial', slug: 'guides-tutorial' },
					]
				},
				{
					label: 'Reference',
					items: [
						{ label: 'API Reference', slug: 'reference-api' },
						{ label: 'CLI Reference', slug: 'reference-cli' },
						{ label: 'TUI Reference', slug: 'reference-tui' },
						{ label: 'Developer Architecture', slug: 'developer-architecture' },
					]
				}
			],
		}),
	],
});
