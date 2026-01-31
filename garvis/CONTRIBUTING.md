# Contributing to Garvis

Thank you for your interest in contributing to Garvis! This document provides guidelines and instructions for contributing.

## 🚀 Getting Started

### Development Setup

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/garvis.git
   cd garvis
   ```

2. **Set up the server**
   ```bash
   cd server
   cp env.example .env
   # Add your API keys to .env
   uv sync
   ```

3. **Set up the client**
   ```bash
   cd ../xr-client
   npm install
   ```

4. **Run in development mode**
   ```bash
   # From root directory
   ./run-all.sh
   ```

## 📝 Code Style

### Python (Server)

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use type hints for function parameters and return values
- Write docstrings for all public functions and classes
- Use async/await for I/O operations

```python
async def my_function(param: str) -> dict:
    """Brief description of function.
    
    Args:
        param: Description of parameter
        
    Returns:
        Description of return value
    """
    pass
```

### TypeScript (Client)

- Use TypeScript strict mode
- Prefer functional components with hooks
- Use explicit types over `any`
- Follow React best practices

```typescript
interface Props {
  value: string
  onChange: (value: string) => void
}

export function MyComponent({ value, onChange }: Props) {
  // ...
}
```

## 🔀 Pull Request Process

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Keep commits focused and atomic
   - Write clear commit messages
   - Add tests if applicable

3. **Test your changes**
   ```bash
   # Server
   cd server && uv run pytest
   
   # Client
   cd xr-client && npm run lint
   ```

4. **Push and create a PR**
   ```bash
   git push origin feature/your-feature-name
   ```

5. **PR Description**
   - Describe what changes you made
   - Explain why the change is needed
   - Link any related issues

## 🏗️ Architecture Guidelines

### Adding New Voice Pipeline Components

Voice components should follow this pattern:

```python
class NewComponent:
    """Description of component."""
    
    def __init__(self, on_output: Callable[[bytes], Awaitable[None]]):
        """Initialize with output callback."""
        self.on_output = on_output
    
    async def connect(self):
        """Establish connection to external service."""
        pass
    
    async def disconnect(self):
        """Clean up resources."""
        pass
    
    async def process(self, data: bytes):
        """Process input and emit output via callback."""
        pass
```

### Adding New MCP Tools

Tools should be:
- **Focused** — Do one thing well
- **Documented** — Clear docstring with Args/Returns
- **Async** — Use async/await for I/O
- **Safe** — Handle errors gracefully

```python
@mcp.tool()
async def my_tool(param: str) -> dict:
    """Brief description for Claude to understand.
    
    Args:
        param: What this parameter does
        
    Returns:
        Dict with result fields
    """
    try:
        # Implementation
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

### Adding New XR Components

XR components should:
- Use React Three Fiber primitives
- Support both AR and VR modes
- Be accessible in the XR space
- Integrate with the Koota ECS if needed

```tsx
import { useXR } from '@react-three/xr'

export function MyXRComponent() {
  const { session } = useXR()
  
  if (!session) return null
  
  return (
    <group position={[0, 1.5, -2]}>
      {/* Your 3D content */}
    </group>
  )
}
```

## 🐛 Bug Reports

When filing a bug report, please include:

1. **Description** — What happened vs what you expected
2. **Steps to reproduce** — Minimal steps to trigger the bug
3. **Environment** — OS, browser, Quest firmware version
4. **Logs** — Server console output, browser console errors
5. **Screenshots/Video** — If applicable

## 💡 Feature Requests

For feature requests, please include:

1. **Problem statement** — What problem does this solve?
2. **Proposed solution** — How would it work?
3. **Alternatives considered** — Other approaches you thought of
4. **Additional context** — Mockups, examples, references

## 📋 Issue Labels

| Label | Description |
|-------|-------------|
| `bug` | Something isn't working |
| `enhancement` | New feature or improvement |
| `documentation` | Docs need updating |
| `good first issue` | Good for newcomers |
| `help wanted` | Extra attention needed |
| `server` | Server-side issue |
| `client` | Client-side issue |
| `voice-pipeline` | Voice processing issue |

## 🙏 Code of Conduct

- Be respectful and inclusive
- Welcome newcomers
- Focus on constructive feedback
- Help others learn

## 📬 Contact

- **Issues** — GitHub Issues for bugs and features
- **Discussions** — GitHub Discussions for questions

---

Thank you for contributing to Garvis! 🎉


