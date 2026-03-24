# LLM Provider Guide - Easy Switching Between AI Models

## Overview

The application now uses a **provider abstraction layer** that makes it trivial to switch between different LLM providers (Claude, Gemini, OpenAI) with **ZERO code changes**.

## Supported Providers

### 1. Claude (Anthropic) - Default
- **Model**: `claude-3-5-sonnet-20241022`
- **Best for**: High-quality reasoning, detailed analysis
- **Cost**: ~$0.05 per audit, ~$0.015 per GPS view
- **Setup**: Get API key from https://console.anthropic.com/

### 2. Gemini (Google)
- **Model**: `models/gemini-2.5-flash`
- **Best for**: Cost-effective, good reasoning, fast responses
- **Cost**: ~$0.01 per audit, ~$0.003 per GPS view (70% cheaper)
- **Setup**: Get API key from https://aistudio.google.com/app/apikey

### 3. OpenAI (GPT)
- **Model**: `gpt-4o`
- **Best for**: Reliable, well-tested
- **Cost**: ~$0.04 per audit, ~$0.012 per GPS view
- **Setup**: Get API key from https://platform.openai.com/api-keys

## How to Switch Providers

### Method 1: Environment Variable (Recommended)

Simply change the `LLM_PROVIDER` variable in your `.env` file:

```bash
# Use Claude (default)
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=sk-ant-...

# OR use Gemini
LLM_PROVIDER=gemini
GOOGLE_API_KEY=your_google_key

# OR use OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

**No code changes needed!** Just restart the server.

### Method 2: Auto-Detection

If you don't set `LLM_PROVIDER`, the system will auto-detect based on which API key is available:

```bash
# Just set the API key you want to use
ANTHROPIC_API_KEY=sk-ant-...
# System will automatically use Claude
```

## Setup Instructions

### Option A: Use Gemini (Recommended - Free Tier Available)

1. **Get API Key**:
   - Go to https://aistudio.google.com/app/apikey
   - Click "Create API Key"
   - Copy the key

2. **Update .env**:
```bash
LLM_PROVIDER=gemini
GOOGLE_API_KEY=your_google_api_key_here
```

3. **Install Gemini SDK**:
```bash
source .venv/bin/activate
pip install google-generativeai
```

4. **Restart Server**:
```bash
# Server will automatically reload
```

### Option B: Use OpenAI

1. **Get API Key**:
   - Go to https://platform.openai.com/api-keys
   - Create new secret key
   - Copy the key

2. **Update .env**:
```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
```

3. **Install OpenAI SDK**:
```bash
source .venv/bin/activate
pip install openai
```

4. **Restart Server**

### Option C: Add Credits to Claude

1. Go to https://console.anthropic.com/
2. Add credits ($5-10 minimum)
3. Server will automatically work (already configured)

## Testing Your Provider

Visit: http://localhost:8000/test-llm

**Success Response**:
```json
{
  "status": "success",
  "provider": "Gemini (Google)",
  "response": "{\"message\": \"LLM is working!\"}"
}
```

**Error Response**:
```json
{
  "status": "error",
  "message": "No LLM provider configured...",
  "provider_type": "claude"
}
```

## What LLM Powers

The LLM provider is used for:

### 1. Resume Auditing
- Infers current role and experience
- Identifies skill strengths and gaps
- Calculates readiness score (25-92)
- Flags career risk signals
- Provides personalized recommendations

### 2. Action Plan Generation
- Creates 3 personalized action items (learn/build/apply)
- Selects optimal career track (management, architecture, fullstack, etc.)
- Provides rationale for recommendations

### 3. Execution Tracker (NEW!)
- Generates 8-10 specific weekly tasks (weeks 1-4)
- Tasks are tailored to candidate's gaps and target role
- Each task includes category and source gap

### 4. 30-Day Checklist (NEW!)
- Generates 5 milestone items at strategic days (3, 7, 14, 21, 30)
- Milestones aligned with action plan
- Context-aware progression

### 5. Career GPS Simulations
- Analyzes trajectory impact of different career moves
- Compares baseline vs simulated paths
- Provides specific recommendations for each simulation

## Architecture Benefits

### Zero Code Changes Required

The abstraction layer (`llm_provider.py`) handles all provider-specific logic:

```python
# Old way (tightly coupled to Claude)
from anthropic import Anthropic
client = Anthropic(api_key=api_key)
response = client.messages.create(...)

# New way (provider-agnostic)
from llm_provider import generate_with_llm
response = generate_with_llm(prompt="...")
# Works with ANY configured provider!
```

### Unified Interface

All providers implement the same interface:
- `generate()` - Generate text from prompt
- `is_available()` - Check if configured
- `get_provider_name()` - Get provider name

### Automatic Fallback

If LLM is not available, the system automatically falls back to rule-based analysis for all features.

## Cost Comparison

### Per 100 Users/Month

| Provider | Audits (100) | GPS Views (500) | Total/Month |
|----------|--------------|-----------------|-------------|
| **Claude** | $5.00 | $7.50 | **$12.50** |
| **Gemini** | $1.00 | $1.50 | **$2.50** (80% cheaper) |
| **OpenAI** | $4.00 | $6.00 | **$10.00** |
| **Rule-Based** | $0 | $0 | **$0** (No AI) |

### Free Tiers

- **Gemini**: Generous free tier (60 requests/minute)
- **OpenAI**: $5 free credits for new accounts
- **Claude**: Trial credits for new accounts

## Provider-Specific Features

### Claude (Anthropic)
✅ Excellent reasoning quality
✅ Long context windows
✅ Good at following JSON schemas
❌ Higher cost
❌ Requires credits

### Gemini (Google)
✅ Very cost-effective
✅ Generous free tier
✅ Fast responses
✅ Good reasoning
⚠️ Slightly less consistent JSON formatting

### OpenAI (GPT)
✅ Well-tested and reliable
✅ Good documentation
✅ Consistent outputs
❌ Moderate cost
⚠️ Rate limits on free tier

## Migration Path

### Current State
- Code is provider-agnostic
- Claude configured but no credits
- Rule-based fallback active

### To Switch to Gemini
1. Get Gemini API key (free)
2. Install: `pip install google-generativeai`
3. Update `.env`: `LLM_PROVIDER=gemini`
4. Restart server
5. Test: `/test-llm`

### To Switch to OpenAI
1. Get OpenAI API key
2. Install: `pip install openai`
3. Update `.env`: `LLM_PROVIDER=openai`
4. Restart server
5. Test: `/test-llm`

### To Add Claude Credits
1. Add credits at https://console.anthropic.com/
2. No other changes needed
3. Server will automatically use Claude

## Code Changes Required: NONE

The abstraction layer means you can switch providers by:
1. Changing environment variable
2. Installing provider SDK
3. Restarting server

**That's it!** No code modifications needed.

## Implementation Details

### Abstraction Layer (`llm_provider.py`)

```python
# Abstract interface
class LLMProvider(ABC):
    def generate(prompt, max_tokens, temperature) -> LLMResponse
    def is_available() -> bool
    def get_provider_name() -> str

# Concrete implementations
- ClaudeProvider (Anthropic)
- GeminiProvider (Google)
- OpenAIProvider (OpenAI)

# Factory pattern
LLMFactory.get_provider(provider_type)
```

### Usage in Application

```python
# Single line to get provider
provider = LLMFactory.get_provider()

# Generate with any provider
response = generate_with_llm(prompt="...")

# Extract JSON (works with all providers)
data = extract_json_from_llm_response(response)
```

## Recommendation

### For Development/Testing
**Use Gemini** - Free tier is generous and quality is good

### For Production
**Start with Gemini** - 80% cheaper than Claude
**Upgrade to Claude** - If you need highest quality reasoning

### For Enterprise
**Use OpenAI** - Most reliable, best support

## Adding New Providers

To add a new provider (e.g., Cohere, Mistral):

1. Create new class in `llm_provider.py`:
```python
class CohereProvider(LLMProvider):
    def generate(self, prompt, ...):
        # Implement Cohere API call
        pass
```

2. Add to factory:
```python
providers = {
    "claude": ClaudeProvider,
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "cohere": CohereProvider,  # Add here
}
```

3. Update `.env`:
```bash
LLM_PROVIDER=cohere
COHERE_API_KEY=...
```

## Current Status

✅ **Abstraction Layer**: Implemented and ready
✅ **Claude Support**: Ready (needs credits)
✅ **Gemini Support**: Ready (needs SDK install + API key)
✅ **OpenAI Support**: Ready (needs SDK install + API key)
✅ **Rule-Based Fallback**: Active and enhanced
✅ **Zero Code Changes**: Switch by environment variable only

## Next Steps

1. **Choose Provider**: Gemini recommended (free tier)
2. **Get API Key**: From provider's console
3. **Install SDK**: `pip install google-generativeai`
4. **Update .env**: Set provider and API key
5. **Restart Server**: Changes take effect
6. **Test**: Visit `/test-llm` endpoint
7. **Use**: Generate audit and see AI-powered analysis

The architecture is now **future-proof** and **provider-agnostic**!
