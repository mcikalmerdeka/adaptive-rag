# Full Stack AI App with Next.js — Project Conventions

Context template for full-stack AI applications using Next.js, React, and modern AI SDKs.

---

## Core Stack

### Frontend
- **Next.js 15** — App Router, Server Components, streaming
- **React 19** — Server Actions, improved hooks
- **TypeScript** — Strict mode, no `any`
- **Tailwind CSS v4** — Utility-first styling
- **shadcn/ui** — Accessible, composable components

### State Management
- **Zustand** — Client state (auth, UI)
- **TanStack Query v5** — Server state, caching
- **Vercel AI SDK** — Streaming chat/AI state

### AI/LLM Integration
- **Vercel AI SDK** — Unified interface for multiple providers
- **LangChain.js** — Complex orchestration when needed
- **OpenAI SDK / Anthropic SDK** — Direct provider access

### Backend
- **Next.js API Routes** — Serverless endpoints
- **Server Actions** — Mutations and data fetching
- **Prisma** — Type-safe database access
- **NextAuth.js v5** — Authentication

### Database
- **PostgreSQL** — Primary database
- **pgvector** — Vector embeddings storage
- **Redis** — Caching, rate limiting

---

## Project Structure

```
project-root/
├── src/
│   ├── app/                    # Next.js App Router
│   │   ├── (auth)/            # Auth route group
│   │   │   ├── login/
│   │   │   ├── register/
│   │   │   └── layout.tsx     # Auth layout
│   │   ├── (main)/            # Main app route group
│   │   │   ├── chat/          # AI chat interface
│   │   │   ├── documents/     # Document management
│   │   │   ├── settings/
│   │   │   └── layout.tsx     # Main app layout
│   │   ├── api/               # API routes
│   │   │   ├── chat/          # Chat API endpoints
│   │   │   │   └── route.ts   # Streaming endpoint
│   │   │   ├── documents/     # Document CRUD
│   │   │   └── auth/[...nextauth]/
│   │   ├── layout.tsx         # Root layout
│   │   ├── page.tsx           # Landing/home
│   │   ├── loading.tsx        # Loading UI
│   │   ├── error.tsx          # Error handling
│   │   └── globals.css        # Global styles + CSS vars
│   ├── components/
│   │   ├── ui/                # shadcn/ui primitives
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── input.tsx
│   │   │   └── ...
│   │   ├── chat/              # Chat-specific components
│   │   │   ├── ChatInput.tsx
│   │   │   ├── ChatMessage.tsx
│   │   │   ├── ChatList.tsx
│   │   │   └── StreamingText.tsx
│   │   ├── layout/            # Layout components
│   │   │   ├── Header.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   └── Footer.tsx
│   │   └── providers/         # Context providers
│   │       ├── AIProvider.tsx
│   │       └── QueryProvider.tsx
│   ├── lib/
│   │   ├── ai/                # AI configuration
│   │   │   ├── config.ts      # AI providers config
│   │   │   ├── prompts.ts     # System prompts
│   │   │   └── tools.ts       # AI tools/functions
│   │   ├── db/                # Database
│   │   │   ├── prisma.ts      # Prisma client
│   │   │   └── schema.prisma  # Database schema
│   │   ├── auth.ts            # NextAuth config
│   │   ├── utils.ts           # Utility functions
│   │   └── constants.ts       # App constants
│   ├── hooks/
│   │   ├── use-chat.ts        # Chat state hook
│   │   ├── use-documents.ts   # Documents data hook
│   │   └── use-user.ts        # User data hook
│   ├── stores/                # Zustand stores
│   │   ├── chat-store.ts
│   │   └── ui-store.ts
│   ├── actions/               # Server Actions
│   │   ├── chat-actions.ts
│   │   ├── document-actions.ts
│   │   └── user-actions.ts
│   └── types/
│       ├── chat.ts
│       ├── document.ts
│       └── api.ts
├── public/                     # Static assets
├── prisma/
│   └── schema.prisma          # Database schema
├── scripts/
│   └── seed.ts                # Database seeding
├── components.json            # shadcn/ui config
├── next.config.js
├── tailwind.config.ts
├── tsconfig.json
└── package.json
```

---

## Development Guidelines

### Server Components vs Client Components

**Use Server Components by default:**
- Data fetching pages
- Static content
- SEO-critical content
- Database queries via Prisma

**Use Client Components sparingly:**
```tsx
"use client"

// - Interactive UI (buttons, forms)
// - Browser APIs (localStorage, clipboard)
// - Real-time features (WebSocket)
// - Third-party JS libraries
// - Hooks that need browser context
```

### Vercel AI SDK Pattern

```tsx
// src/lib/ai/config.ts
import { createOpenAI } from '@ai-sdk/openai';
import { createAnthropic } from '@ai-sdk/anthropic';

export const openai = createOpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

export const anthropic = createAnthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});
```

```tsx
// src/app/api/chat/route.ts
import { streamText } from 'ai';
import { openai } from '@/lib/ai/config';

export async function POST(req: Request) {
  const { messages } = await req.json();

  const result = streamText({
    model: openai('gpt-4'),
    messages,
    system: "You are a helpful AI assistant.",
    tools: {
      // Define tools here
    },
  });

  return result.toDataStreamResponse();
}
```

```tsx
// src/components/chat/ChatInput.tsx
"use client"

import { useChat } from 'ai/react';

export function ChatInput() {
  const { messages, input, handleInputChange, handleSubmit, isLoading } = useChat();

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-auto">
        {messages.map(m => (
          <div key={m.id} className={m.role === 'user' ? 'user' : 'assistant'}>
            {m.content}
          </div>
        ))}
      </div>
      
      <form onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={handleInputChange}
          placeholder="Type a message..."
          disabled={isLoading}
        />
        <button type="submit" disabled={isLoading}>
          Send
        </button>
      </form>
    </div>
  );
}
```

### Server Actions Pattern

```tsx
// src/actions/chat-actions.ts
"use server"

import { revalidatePath } from "next/cache";
import { prisma } from "@/lib/db/prisma";

export async function saveConversation(
  userId: string,
  messages: Array<{ role: string; content: string }>
) {
  try {
    const conversation = await prisma.conversation.create({
      data: {
        userId,
        messages: {
          create: messages.map((m, index) => ({
            role: m.role,
            content: m.content,
            order: index,
          })),
        },
      },
    });
    
    revalidatePath("/chat");
    return { success: true, conversation };
  } catch (error) {
    return { success: false, error: "Failed to save conversation" };
  }
}
```

### TanStack Query Pattern

```tsx
// src/hooks/use-documents.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export function useDocuments() {
  return useQuery({
    queryKey: ["documents"],
    queryFn: async () => {
      const res = await fetch("/api/documents");
      if (!res.ok) throw new Error("Failed to fetch documents");
      return res.json();
    },
  });
}

export function useCreateDocument() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (document: CreateDocumentInput) => {
      const res = await fetch("/api/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(document),
      });
      if (!res.ok) throw new Error("Failed to create document");
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}
```

### Zustand Store Pattern

```tsx
// src/stores/chat-store.ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ChatState {
  selectedModel: string;
  temperature: number;
  setModel: (model: string) => void;
  setTemperature: (temp: number) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set) => ({
      selectedModel: "gpt-4",
      temperature: 0.7,
      setModel: (model) => set({ selectedModel: model }),
      setTemperature: (temp) => set({ temperature: temp }),
    }),
    { name: "chat-settings" }
  )
);
```

---

## Database Schema (Prisma)

```prisma
// prisma/schema.prisma

generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model Account {
  id                String  @id @default(cuid())
  userId            String
  type              String
  provider          String
  providerAccountId String
  refresh_token     String? @db.Text
  access_token      String? @db.Text
  expires_at        Int?
  token_type        String?
  scope             String?
  id_token          String? @db.Text
  session_state     String?

  user User @relation(fields: [userId], references: [id], onDelete: Cascade)

  @@unique([provider, providerAccountId])
}

model User {
  id            String    @id @default(cuid())
  email         String    @unique
  name          String?
  image         String?
  emailVerified DateTime?
  accounts      Account[]
  conversations Conversation[]
  documents     Document[]
  createdAt     DateTime  @default(now())
  updatedAt     DateTime  @updatedAt
}

model Conversation {
  id        String    @id @default(cuid())
  title     String?
  userId    String
  user      User      @relation(fields: [userId], references: [id], onDelete: Cascade)
  messages  Message[]
  createdAt DateTime  @default(now())
  updatedAt DateTime  @updatedAt
}

model Message {
  id             String       @id @default(cuid())
  role           String       // user, assistant, system
  content        String       @db.Text
  conversationId String
  conversation   Conversation @relation(fields: [conversationId], references: [id], onDelete: Cascade)
  createdAt      DateTime     @default(now())
}

model Document {
  id          String   @id @default(cuid())
  title       String
  content     String   @db.Text
  embedding   Unsupported("vector(1536)")?
  userId      String
  user        User     @relation(fields: [userId], references: [id], onDelete: Cascade)
  createdAt   DateTime @default(now())
  updatedAt   DateTime @updatedAt

  @@index([userId])
}
```

---

## AI Tools/Functions Pattern

```tsx
// src/lib/ai/tools.ts
import { tool } from "ai";
import { z } from "zod";
import { prisma } from "@/lib/db/prisma";

export const searchDocuments = tool({
  description: "Search user's documents for relevant information",
  parameters: z.object({
    query: z.string().describe("The search query"),
  }),
  execute: async ({ query }) => {
    // Implement vector search or full-text search
    const documents = await prisma.document.findMany({
      where: {
        OR: [
          { title: { contains: query, mode: "insensitive" } },
          { content: { contains: query, mode: "insensitive" } },
        ],
      },
      take: 5,
    });
    
    return documents.map(d => ({
      title: d.title,
      content: d.content.substring(0, 500),
    }));
  },
});

export const saveToConversation = tool({
  description: "Save important information to the conversation",
  parameters: z.object({
    summary: z.string().describe("Summary of the information"),
  }),
  execute: async ({ summary }) => {
    // Implementation
    return { saved: true, summary };
  },
});
```

---

## Component Patterns

### shadcn/ui Component Usage

```tsx
// Example: Building a form with shadcn/ui
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";

export function DocumentForm() {
  const form = useForm<CreateDocumentInput>({
    resolver: zodResolver(createDocumentSchema),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Create Document</CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)}>
            <FormField
              control={form.control}
              name="title"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Title</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <Button type="submit">Create</Button>
          </form>
        </Form>
      </CardContent>
    </Card>
  );
}
```

### Loading States

```tsx
// src/app/chat/loading.tsx
import { Skeleton } from "@/components/ui/skeleton";

export default function ChatLoading() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-3/4" />
    </div>
  );
}
```

### Error Handling

```tsx
// src/app/chat/error.tsx
"use client"

import { Button } from "@/components/ui/button";

export default function ChatError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[400px]">
      <h2 className="text-xl font-bold mb-4">Something went wrong!</h2>
      <p className="text-muted-foreground mb-4">{error.message}</p>
      <Button onClick={reset}>Try again</Button>
    </div>
  );
}
```

---

## Environment Configuration

### .env.local

```bash
# Database
DATABASE_URL="postgresql://user:password@localhost:5432/aiapp"

# NextAuth
NEXTAUTH_URL="http://localhost:3000"
NEXTAUTH_SECRET="your-secret-key"

# OAuth Providers
GITHUB_CLIENT_ID=""
GITHUB_CLIENT_SECRET=""
GOOGLE_CLIENT_ID=""
GOOGLE_CLIENT_SECRET=""

# AI Providers
OPENAI_API_KEY=""
ANTHROPIC_API_KEY=""

# Vector Search
OPENAI_EMBEDDING_MODEL="text-embedding-3-small"
```

---

## Code Quality Standards

### TypeScript Configuration

```json
// tsconfig.json
{
  "compilerOptions": {
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

### ESLint Configuration

```json
// .eslintrc.json
{
  "extends": ["next/core-web-vitals", "next/typescript"],
  "rules": {
    "@typescript-eslint/no-unused-vars": "error",
    "@typescript-eslint/no-explicit-any": "error"
  }
}
```

### Key Patterns

1. **Path Aliases**: Use `@/` for all imports from `src/`
2. **No `any`**: Strict TypeScript — use `unknown` if type is uncertain
3. **Named Exports**: Prefer named exports over default exports
4. **Colocation**: Keep related files close (component + test + styles)
5. **Server-First**: Start with Server Components, add `"use client"` only when needed

---

## Performance Guidelines

### Server Components
- Fetch data directly in Server Components when possible
- Use `unstable_cache` for expensive operations
- Leverage streaming with `loading.tsx`

### Client Components
- Use `React.memo()` for expensive renders
- Use `useMemo()` and `useCallback()` appropriately
- Lazy load heavy components with `next/dynamic`

### Images
- Always use `next/image` for optimized images
- Set appropriate `sizes` prop for responsive images

### Fonts
- Use `next/font` for optimized font loading
- Preload critical fonts