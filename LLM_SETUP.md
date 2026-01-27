# LLM Setup for Ask ED Chatbot

The Ask ED chatbot uses free LLM services to provide intelligent responses. Here's how to configure it.

## Current Issue: Hugging Face 410 Errors

Hugging Face free models are currently returning 410 (Gone) errors, which means those model endpoints are no longer available. The chatbot will automatically fall back to rule-based responses.

## Recommended Free LLM Options

### Option 1: Groq (Recommended - Fast & Free)

Groq offers a free tier with very fast responses.

1. **Get a free API key**:
   - Go to https://console.groq.com/
   - Sign up for a free account
   - Create an API key

2. **Set environment variables**:
   ```bash
   export LLM_PROVIDER="groq"
   export LLM_API_KEY="your_groq_api_key_here"
   ```

3. **Restart the Flask server**

### Option 2: Ollama (Local - Completely Free)

Ollama runs models locally on your machine - completely free and private.

1. **Install Ollama**:
   - Download from https://ollama.ai
   - Install and start Ollama

2. **Pull a model**:
   ```bash
   ollama pull llama3.2
   # or
   ollama pull mistral
   ```

3. **Set environment variables**:
   ```bash
   export LLM_PROVIDER="ollama"
   export LLM_MODEL="llama3.2"
   ```

4. **Restart the Flask server**

### Option 3: Together AI (Free Tier)

Together AI offers free tier access.

1. **Get API key** from https://api.together.xyz/

2. **Set environment variables**:
   ```bash
   export LLM_PROVIDER="together"
   export LLM_API_KEY="your_together_api_key"
   ```

### Option 4: Continue with Rule-Based (No Setup)

The chatbot works perfectly fine without an LLM - it will use intelligent rule-based responses based on:
- Your repository data
- EDGY framework knowledge
- Notion knowledge base (if configured)

## Testing

After setting up an LLM provider, test it:

```bash
curl -X POST http://localhost:5000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is EDGY?"}'
```

Check the server logs to see if the LLM is being used or if it's falling back to rule-based responses.

## Troubleshooting

- **410 Errors**: Model endpoint no longer available - try a different provider
- **401 Errors**: Authentication required - set LLM_API_KEY
- **503 Errors**: Model is loading - wait a moment and try again
- **Timeout**: Model is slow or unavailable - try a different provider

## Default Behavior

If no LLM is configured or all attempts fail, the chatbot automatically uses rule-based responses, which work well for most questions about your repository and EDGY concepts.

