# Environment Setup

Create `backend/.env` with the following variables:

```
AI_API_KEY=your_api_key_here
AI_BASE_URL=https://api.deepseek.com
AI_MODEL_NAME=deepseek-chat
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

- **AI_API_KEY**: Your AI provider API key (DeepSeek, OpenAI, or compatible)
- **AI_BASE_URL**: API base URL
- **AI_MODEL_NAME**: Model name to use
- **CORS_ORIGINS**: Allowed CORS origins (comma-separated)
