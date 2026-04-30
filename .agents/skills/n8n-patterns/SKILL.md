---
name: n8n-workflow-patterns
description: Best practices and patterns for building production-ready n8n workflows. Use when designing, building, or debugging n8n automation workflows.
---

# n8n Workflow Patterns Guide

## Overview

n8n is a workflow automation platform that connects apps and services. This skill covers patterns for building maintainable, reliable, and scalable workflows.

---

## When to Use This Skill

- Designing new n8n workflows
- Refactoring existing workflows for better reliability
- Debugging failing workflows
- Building integrations between services
- Creating scheduled automation

---

## Core Principles

### 1. Workflow Design Patterns

**Single Responsibility**
Each workflow should do one thing well. Complex automations should be split into multiple workflows connected via:
- Execute Workflow node
- Webhook triggers
- n8n API

**Fail-Fast and Loud**
- Use Error Trigger workflows for centralized error handling
- Never silently swallow errors
- Send notifications on failures

**Idempotency**
Design workflows to be safely re-runnable:
- Check if action already performed before doing it
- Use deduplication keys
- Handle duplicate webhook calls gracefully

### 2. Node Patterns

**HTTP Request Node**
```
Best Practices:
- Always set timeout (default 5 min is often too long)
- Handle 4xx and 5xx errors explicitly
- Use pagination for large datasets
- Implement retry logic for transient failures
```

**Code Node**
```javascript
// Good: Input validation
const input = $input.first().json;
if (!input.email) {
  throw new Error('Email is required');
}

// Good: Error handling with context
try {
  const result = await someAsyncOperation();
  return [{ json: result }];
} catch (error) {
  // Log context for debugging
  console.error('Operation failed:', { input: input.id, error: error.message });
  throw error;
}
```

**Function Node (Legacy)**
Prefer Code Node over Function Node in new workflows.

### 3. Data Handling

**Passing Data Between Nodes**
```javascript
// Access previous node data
const items = $input.all();
const firstItem = $input.first().json;

// Reference specific node output
const data = $('Node Name').first().json;
```

**Transforming Data**
```javascript
// Map over items
const results = items.map(item => ({
  json: {
    id: item.json.id,
    name: item.json.name.toUpperCase(),
    processed: true,
  }
}));
return results;
```

### 4. Error Handling

**Try-Catch Pattern**
```javascript
try {
  // Risky operation
  const result = await riskyCall();
  return [{ json: { success: true, data: result } }];
} catch (error) {
  // Return error in structured format
  return [{
    json: {
      success: false,
      error: error.message,
      timestamp: new Date().toISOString(),
    }
  }];
}
```

**Error Workflow**
Create a dedicated workflow for error handling:
- Trigger: Error Trigger node
- Actions: Log to database, send Slack/email notification, retry logic

### 5. Credential Management

**Security Best Practices**
- Never hardcode credentials in Code nodes
- Always use n8n credential system
- Rotate credentials regularly
- Use least-privilege access for service accounts

**Custom Credentials**
For custom APIs, create a generic credential type or use HTTP Request node with OAuth.

---

## Workflow Architecture Patterns

### Pattern 1: Webhook Receiver
```
Webhook Node → Validation → Processing → Response
                    ↓
              Error Handler
```

Use for: Real-time integrations, external service callbacks

### Pattern 2: Scheduled Job
```
Schedule Trigger → Data Fetch → Transform → Action → Notification
```

Use for: Daily reports, data sync, cleanup tasks

### Pattern 3: Event-Driven Chain
```
Trigger → Filter → Enrich → Route → Multiple Actions
                              ↙      ↓      ↘
                           Action1 Action2 Action3
```

Use for: Complex automation with conditional branches

### Pattern 4: Workflow Orchestration
```
Main Workflow → Execute Workflow (Sub-workflow 1)
            → Execute Workflow (Sub-workflow 2)
            → Aggregate Results
```

Use for: Complex multi-step processes, reusable components

---

## Debugging Workflows

### Enable Execution Logging
```
Settings → Log Execution → Enable
```

### Use Debug Nodes
Insert Set nodes to inspect data at specific points:
```javascript
// Debug node output
{
  "debug_stage": "after_api_call",
  "raw_response": $input.first().json,
  "item_count": $input.all().length
}
```

### Common Issues

**Issue: Data not passing between nodes**
- Check if previous node outputs items
- Verify item structure matches expected input
- Use Code node to inspect `$input`

**Issue: Workflow times out**
- Add pagination for large datasets
- Use Split In Batches node
- Consider splitting into multiple workflows

**Issue: Rate limiting**
- Add Wait nodes between API calls
- Implement exponential backoff
- Use queue-based processing

---

## Performance Optimization

### Batch Processing
```
Split In Batches (100 items/batch) → Process → Wait 1s → Loop
```

### Parallel Processing
```
                    → Process A
Split → Route       → Process B
                    → Process C
```

### Caching
Use the Static Data feature to cache:
- Access tokens
- Reference data
- Configuration

---

## Code Node Utilities

### Common Helpers
```javascript
// Date formatting
const now = new Date().toISOString();
const formatted = new Date().toLocaleDateString('en-US');

// Generate unique ID
const id = Date.now().toString(36) + Math.random().toString(36).substr(2);

// Sleep function
const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// Retry wrapper
async function withRetry(fn, maxAttempts = 3) {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      return await fn();
    } catch (error) {
      if (i === maxAttempts - 1) throw error;
      await sleep(1000 * (i + 1)); // Exponential backoff
    }
  }
}
```

---

## Resources

- **n8n Docs**: https://docs.n8n.io/
- **Workflow Templates**: https://n8n.io/workflows
- **Community Forum**: https://community.n8n.io/
- **Node Reference**: https://docs.n8n.io/integrations/builtin/