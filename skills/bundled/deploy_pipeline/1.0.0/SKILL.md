---
name: Deploy Pipeline
module_id: skill.deploy_pipeline
version: 1.0.0
category: skill
description: Full deployment workflow with testing, containerization, and rollback
tags: [deploy, pipeline, docker, ci-cd, production]
enabled_by_default: true
---

# Deploy Pipeline

## When to Use
Activate when deploying code to production, staging, or any environment.

## Procedure

### Step 1: Pre-Deploy Checks
1. Verify current branch and git status
2. Run test suite (`pytest`, `npm test`, etc.)
3. Check for uncommitted changes
4. Verify environment variables are set

### Step 2: Build
1. If Docker: Build container image with proper tags
2. If static: Run build command (`npm run build`, etc.)
3. Tag the release in git

### Step 3: Deploy
1. Push to target environment
2. Run database migrations if needed
3. Verify health endpoint responds
4. Check logs for startup errors

### Step 4: Verify
1. Hit health check endpoint
2. Run smoke tests
3. Monitor error rates for 5 minutes
4. Notify user of deployment status

### Step 5: Rollback (if needed)
1. Revert to previous container/build
2. Rollback database migrations
3. Verify recovery
4. Post-mortem analysis
