---
name: ai-integration
description: Patterns and best practices for integrating AI/LLM capabilities into applications. Use when implementing chat, RAG, agents, or other AI features.
---

# AI Integration Patterns Guide

## Overview

This skill covers patterns for integrating Large Language Models (LLMs) into applications effectively and safely.

---

## When to Use This Skill

- Building chat interfaces
- Implementing RAG (Retrieval-Augmented Generation)
- Creating AI agents
- Adding AI-powered features to existing apps
- Choosing between different AI approaches

---

## Core Patterns

### 1. Chat Interface

**Basic Streaming Chat**
```typescript
// Server-side (API route)
import { streamText } from 'ai';
import { openai } from '@/lib/ai/providers';

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = streamText({
    model: openai('gpt-4'),
    messages,
    system: "You are a helpful assistant.",
  });

  return result.toDataStreamResponse();
}
```

```typescript
// Client-side (React)
import { useChat } from 'ai/react';

function ChatComponent() {
  const { messages, input, handleInputChange, handleSubmit } = useChat();

  return (
    <form onSubmit={handleSubmit}>
      {messages.map(m => (
        <div key={m.id}>{m.content}</div>
      ))}
      <input 
        value={input} 
        onChange={handleInputChange}
        placeholder="Type a message..."
      />
    </form>
  );
}
```

### 2. RAG (Retrieval-Augmented Generation)

**Basic RAG Flow**
```
User Query → Embed Query → Vector Search → Retrieve Context → 
Augment Prompt → Generate Response → Return with Sources
```

**Implementation Pattern**
```typescript
async function generateWithRAG(query: string) {
  // 1. Generate embedding for query
  const embedding = await generateEmbedding(query);
  
  // 2. Search vector database
  const relevantDocs = await vectorDB.query({
    embedding,
    topK: 5,
  });
  
  // 3. Build augmented prompt
  const context = relevantDocs.map(d => d.content).join('\n\n');
  const prompt = `Context:\n${context}\n\nQuestion: ${query}`;
  
  // 4. Generate response
  const response = await llm.generate(prompt);
  
  // 5. Return with source citations
  return {
    answer: response,
    sources: relevantDocs.map(d => ({
      title: d.title,
      url: d.url,
    })),
  };
}
```

### 3. Tool Use / Function Calling

**Defining Tools**
```typescript
import { tool } from 'ai';
import { z } from 'zod';

const searchDocuments = tool({
  description: "Search the knowledge base for relevant information",
  parameters: z.object({
    query: z.string().describe("The search query"),
  }),
  execute: async ({ query }) => {
    // Implementation
    return await searchKnowledgeBase(query);
  },
});

const calculateMortgage = tool({
  description: "Calculate monthly mortgage payment",
  parameters: z.object({
    principal: z.number().describe("Loan amount"),
    rate: z.number().describe("Annual interest rate (decimal)"),
    years: z.number().describe("Loan term in years"),
  }),
  execute: async ({ principal, rate, years }) => {
    const monthlyRate = rate / 12;
    const numPayments = years * 12;
    const payment = 
      (principal * monthlyRate * Math.pow(1 + monthlyRate, numPayments)) /
      (Math.pow(1 + monthlyRate, numPayments) - 1);
    return { monthlyPayment: payment.toFixed(2) };
  },
});
```

**Using Tools**
```typescript
const result = await generateText({
  model: openai('gpt-4'),
  tools: { searchDocuments, calculateMortgage },
  prompt: userMessage,
});
```

### 4. Multi-Step Agents

**Simple Agent Loop**
```typescript
async function runAgent(userInput: string, maxSteps = 5) {
  const messages: Message[] = [
    { role: 'system', content: 'You are a helpful agent...' },
    { role: 'user', content: userInput },
  ];
  
  for (let i = 0; i < maxSteps; i++) {
    const response = await llm.generate({
      messages,
      tools: availableTools,
    });
    
    if (response.finishReason === 'stop') {
      return response.content;
    }
    
    if (response.toolCalls) {
      // Execute tool calls
      for (const call of response.toolCalls) {
        const result = await executeTool(call);
        messages.push({
          role: 'tool',
          tool_call_id: call.id,
          content: JSON.stringify(result),
        });
      }
    }
  }
  
  return "Maximum steps reached";
}
```

---

## Best Practices

### 1. Prompt Engineering

**System Prompts**
- Be specific about the assistant's role
- Include constraints and boundaries
- Provide output format examples

```
You are a customer support agent for TechCorp.
- Be friendly but professional
- If you don't know something, say so
- Always verify account details before making changes
- Format responses in markdown
```

**Few-Shot Prompting**
Include examples for complex tasks:
```
Classify the sentiment of the following text.

Examples:
Text: "I love this product!"
Sentiment: Positive

Text: "Terrible experience, never again"
Sentiment: Negative

Text: {{user_input}}
Sentiment:
```

### 2. Context Management

**Token Budgets**
- Track token usage
- Implement context window management
- Summarize long conversations when needed

**Relevant Context Selection**
- Don't dump entire documents into context
- Use semantic search to find relevant chunks
- Prioritize recent and relevant information

### 3. Error Handling

**Common Errors**
- Rate limits: Implement exponential backoff
- Timeout: Break requests into smaller chunks
- Content policy: Handle refusals gracefully
- JSON parsing: Use structured output when possible

```typescript
try {
  const response = await llm.generate(prompt);
  return response;
} catch (error) {
  if (error.code === 'rate_limit_exceeded') {
    await sleep(1000);
    return retry(prompt);
  }
  if (error.code === 'content_policy_violation') {
    return { error: 'I cannot respond to that request' };
  }
  throw error;
}
```

### 4. Safety & Guardrails

**Input Validation**
- Sanitize user inputs
- Limit input length
- Validate against injection attacks

**Output Filtering**
- Check for PII in outputs
- Filter inappropriate content
- Add human review for sensitive actions

**Cost Controls**
- Set token limits per request
- Cache common responses
- Monitor usage and set budgets

---

## Provider Selection Guide

| Use Case | Recommended Provider | Model |
|----------|---------------------|-------|
| General chat | OpenAI / Anthropic | GPT-4 / Claude Sonnet |
| Reasoning tasks | OpenAI / Anthropic | o3 / Claude Opus |
| Long context | Google | Gemini 2.5 Pro |
| Cost-sensitive | OpenAI | GPT-4o-mini |
| Code generation | Anthropic | Claude Sonnet |
| Multimodal | OpenAI / Google | GPT-4o / Gemini |

---

## Evaluation

**Test Your AI Integration**

1. **Create test cases** with expected outputs
2. **Test edge cases** (empty input, very long input, special characters)
3. **Measure latency** and cost per request
4. **Monitor error rates** and failure modes

**Example Evaluation Questions**
- Can the system handle ambiguous queries?
- Does it refuse inappropriate requests?
- Are sources correctly cited in RAG?
- Does it maintain context across multiple turns?

---

## Resources

- **Vercel AI SDK**: https://sdk.vercel.ai/docs
- **OpenAI API**: https://platform.openai.com/docs
- **Anthropic API**: https://docs.anthropic.com/
- **LangChain**: https://python.langchain.com/ / https://js.langchain.com/