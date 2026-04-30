---
name: deployment-patterns
description: Deployment patterns and best practices for various platforms. Use when setting up deployment pipelines, choosing infrastructure, or configuring CI/CD.
---

# Deployment Patterns Guide

## Overview

This skill covers deployment patterns for different types of applications across various platforms.

---

## When to Use This Skill

- Setting up deployment for a new project
- Choosing between deployment platforms
- Configuring CI/CD pipelines
- Migrating between hosting providers
- Setting up staging/production environments

---

## Platform Selection Guide

### Vercel
**Best for:** Next.js, React, static sites

**Pros:**
- Zero-config for Next.js
- Automatic preview deployments
- Edge functions
- Built-in analytics

**When to use:**
- Frontend applications
- Full-stack Next.js apps
- JAMstack sites

**Configuration:**
```json
// vercel.json
{
  "buildCommand": "npm run build",
  "outputDirectory": ".next",
  "framework": "nextjs",
  "rewrites": [
    { "source": "/api/(.*)", "destination": "/api/$1" }
  ]
}
```

### Railway / Render / Fly.io
**Best for:** Full-stack apps, APIs, databases

**Pros:**
- Easy environment variable management
- Automatic HTTPS
- Native Docker support
- Good for Node.js/Python/Go

**When to use:**
- Backend APIs
- Full-stack apps with persistent storage
- Applications needing databases

### AWS (ECS, Lambda, EC2)
**Best for:** Enterprise, complex infrastructure

**Pros:**
- Full control
- Scalable
- Extensive service ecosystem

**When to use:**
- Production enterprise apps
- Complex microservices
- When you need specific AWS services

**Lambda Example:**
```yaml
# serverless.yml
service: my-api

provider:
  name: aws
  runtime: nodejs20.x
  region: us-east-1

functions:
  api:
    handler: dist/index.handler
    events:
      - httpApi: '*'
```

### Docker + VPS (DigitalOcean, Hetzner, etc.)
**Best for:** Cost-conscious, full control

**Pros:**
- Cheapest for steady traffic
- Full control over server
- No vendor lock-in

**When to use:**
- Side projects
- Predictable traffic
- Learning/DevOps practice

---

## CI/CD Patterns

### GitHub Actions

**Basic Setup**
```yaml
# .github/workflows/deploy.yml
name: Deploy

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm run lint
      - run: npm run test
      - run: npm run build

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - name: Deploy to Vercel
        uses: vercel/action-deploy@v1
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
```

**Matrix Testing**
```yaml
strategy:
  matrix:
    node-version: [18, 20, 21]
    os: [ubuntu-latest, windows-latest]
```

### Environment Strategy

**Typical Setup**
```
Development → Staging → Production
     ↓             ↓           ↓
  Local        Preview     Live
```

**Branch-Based**
```
feature/*   → Deploy to Preview/Staging
main        → Deploy to Production
```

---

## Database Deployment

### PostgreSQL Options

| Platform | Type | Best For |
|----------|------|----------|
| **Neon** | Serverless | Auto-scaling, scale-to-zero |
| **Supabase** | Managed | Full backend-as-a-service |
| **Railway** | Managed | Simple setup, good pricing |
| **AWS RDS** | Managed | Enterprise, compliance needs |
| **Self-hosted** | VPS | Cost control, full access |

### Migration Strategy

**Prisma (Node.js)**
```bash
# Generate migration
npx prisma migrate dev --name add_user_table

# Deploy migration
npx prisma migrate deploy
```

**Alembic (Python)**
```bash
# Generate migration
alembic revision --autogenerate -m "Add user table"

# Run migration
alembic upgrade head
```

---

## Environment Configuration

### Environment Variables

**Required Variables**
```bash
# App
NODE_ENV=production
PORT=3000

# Database
DATABASE_URL=postgresql://...

# Auth
JWT_SECRET=...
NEXTAUTH_SECRET=...

# APIs
OPENAI_API_KEY=...
```

**Configuration Pattern**
```typescript
// config.ts
const config = {
  development: {
    apiUrl: 'http://localhost:3000',
    debug: true,
  },
  production: {
    apiUrl: process.env.API_URL,
    debug: false,
  },
}[process.env.NODE_ENV || 'development'];
```

---

## Docker Deployment

### Dockerfile Patterns

**Node.js**
```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY package*.json ./
EXPOSE 3000
CMD ["node", "dist/index.js"]
```

**Python**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy and install dependencies
COPY pyproject.toml ./
RUN uv pip install --system -e "."

# Copy source
COPY src/ ./src/

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
      - DATABASE_URL=postgresql://postgres:password@db:5432/myapp
    depends_on:
      - db

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=myapp
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

---

## Health Checks & Monitoring

### Health Check Endpoint

```typescript
// Simple health check
app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    timestamp: new Date().toISOString(),
    version: process.env.npm_package_version
  });
});

// With dependencies check
app.get('/health', async (req, res) => {
  const checks = {
    database: await checkDatabase(),
    cache: await checkCache(),
    externalApi: await checkExternalApi(),
  };
  
  const healthy = Object.values(checks).every(c => c.status === 'ok');
  
  res.status(healthy ? 200 : 503).json({
    status: healthy ? 'ok' : 'error',
    checks,
    timestamp: new Date().toISOString(),
  });
});
```

### Monitoring Tools

| Tool | Purpose | Cost |
|------|---------|------|
| **Sentry** | Error tracking | Free tier |
| **Datadog** | Full observability | Paid |
| **Grafana Cloud** | Metrics/dashboards | Free tier |
| **UptimeRobot** | Uptime monitoring | Free tier |

---

## Security Checklist

- [ ] HTTPS enforced
- [ ] Secrets in environment variables (never in code)
- [ ] Database credentials rotated regularly
- [ ] CORS properly configured
- [ ] Rate limiting implemented
- [ ] Input validation on all endpoints
- [ ] Dependencies kept up to date
- [ ] Security headers set (HSTS, CSP, etc.)

---

## Troubleshooting

### Common Issues

**Build fails**
- Check Node.js/Python version matches
- Clear cache and reinstall dependencies
- Check for missing environment variables

**Deployment succeeds but app crashes**
- Check logs: `vercel logs` / `railway logs` / `docker logs`
- Verify environment variables are set
- Check database connectivity

**Slow cold starts**
- Use smaller dependencies
- Implement connection pooling
- Use edge functions where appropriate

---

## Resources

- **Vercel Docs**: https://vercel.com/docs
- **Railway Docs**: https://docs.railway.app/
- **Docker Docs**: https://docs.docker.com/
- **GitHub Actions**: https://docs.github.com/en/actions