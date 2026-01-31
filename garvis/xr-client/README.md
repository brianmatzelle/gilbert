# Garvis XR Client

WebXR voice assistant client built with React Three Fiber for immersive AR/VR experiences.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        XR Client                             │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                   React Application                     │ │
│  │                                                         │ │
│  │  ┌──────────────┐    ┌──────────────┐                  │ │
│  │  │   App.tsx    │───▶│   XRScene    │                  │ │
│  │  │  (Entry)     │    │  (3D World)  │                  │ │
│  │  └──────────────┘    └──────┬───────┘                  │ │
│  │                             │                           │ │
│  │         ┌───────────────────┼───────────────────┐      │ │
│  │         ▼                   ▼                   ▼      │ │
│  │  ┌────────────┐    ┌──────────────┐    ┌───────────┐  │ │
│  │  │  ChatLog   │    │   ECS World  │    │   Voice   │  │ │
│  │  │  (Visor)   │    │   (Koota)    │    │   Hook    │  │ │
│  │  └────────────┘    └──────────────┘    └─────┬─────┘  │ │
│  │                                              │        │ │
│  │                                              ▼        │ │
│  │                                      ┌────────────┐   │ │
│  │                                      │GarvisClient│   │ │
│  │                                      │ WebSocket  │   │ │
│  │                                      └─────┬──────┘   │ │
│  └────────────────────────────────────────────┼──────────┘ │
│                                               │            │
│                    WebSocket + WebAudio       │            │
└───────────────────────────────────────────────┼────────────┘
                                                │
                                                ▼
                                        Garvis Server
```

## 🚀 Quick Start

```bash
# Install dependencies
npm install

# Development (with HTTPS for WebXR + Microphone)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## 🔧 Tech Stack

| Technology | Purpose |
|------------|---------|
| [Vite](https://vitejs.dev/) | Build tool with HMR |
| [React 19](https://react.dev/) | UI framework |
| [TypeScript](https://www.typescriptlang.org/) | Type safety |
| [Three.js](https://threejs.org/) | 3D rendering |
| [@react-three/fiber](https://r3f.docs.pmnd.rs/) | React renderer for Three.js |
| [@react-three/xr](https://github.com/pmndrs/xr) | WebXR integration |
| [@react-three/drei](https://github.com/pmndrs/drei) | Useful R3F helpers |
| [Koota](https://github.com/pmndrs/koota) | ECS state management |

## 📁 Project Structure

```
xr-client/
├── src/
│   ├── main.tsx              # Entry point
│   ├── App.tsx               # Main app + XR setup
│   ├── App.css               # Global styles
│   ├── index.css             # Reset styles
│   │
│   ├── components/
│   │   ├── video/
│   │   │   └── VideoWindow.tsx   # 3D video player panel
│   │   └── visor/
│   │       └── ChatLog.tsx       # HUD chat overlay
│   │
│   ├── ecs/
│   │   ├── traits.ts         # State definitions (incl. ActiveVideo)
│   │   ├── world.ts          # World initialization
│   │   └── actions.ts        # State mutations (incl. setActiveVideo)
│   │
│   └── voice/
│       ├── garvis-client.ts      # WebSocket client (handles stream_url)
│       └── useVoiceAssistant.ts  # React hook
│
├── public/                   # Static assets
├── dist/                     # Build output
│
├── vite.config.ts           # Vite + proxy configuration
├── tsconfig.json            # TypeScript config
└── package.json             # Dependencies (incl. hls.js)
```

## 🎤 Voice Client

The `GarvisClient` class handles all voice communication with the server.

### Features

- **Microphone capture** — WebAudio API with echo cancellation
- **Audio streaming** — 16-bit PCM @ 16kHz via WebSocket
- **Transcript handling** — Real-time user and assistant text
- **TTS playback** — MP3 streaming via HTML5 Audio

### Usage

```typescript
import { GarvisClient } from './voice/garvis-client'

const client = new GarvisClient({
  onConnected: () => console.log('Connected!'),
  onDisconnected: () => console.log('Disconnected'),
  onTranscript: (text, isFinal, role) => {
    console.log(`${role}: ${text} (final: ${isFinal})`)
  },
  onListening: (isListening) => {
    console.log(`Listening: ${isListening}`)
  },
  onSpeaking: (isSpeaking) => {
    console.log(`Speaking: ${isSpeaking}`)
  },
  onStreamUrl: (url) => {
    // Open video player with this URL
    console.log(`Stream URL: ${url}`)
  },
  onError: (error) => console.error(error)
})

// Connect to server
await client.connect('/ws/voice')

// Interrupt assistant speech
client.interrupt()

// Disconnect when done
client.disconnect()
```

### React Hook

```typescript
import { useVoiceAssistant } from './voice/useVoiceAssistant'

function MyComponent() {
  useVoiceAssistant({ enabled: true })
  // Voice assistant is now active
}
```

## 🥽 XR Usage

### Entering XR

The app attempts AR first (Quest 3 passthrough), falling back to VR:

```typescript
const handleEnterXR = async () => {
  try {
    await xrStore.enterAR()  // Quest 3 passthrough
  } catch {
    await xrStore.enterVR()  // VR fallback
  }
}
```

### Accessing from Quest 3

1. Find your computer's LAN IP address:
   ```bash
   # macOS
   ipconfig getifaddr en0
   
   # Linux
   hostname -I
   
   # Windows
   ipconfig | findstr IPv4
   ```

2. On Quest 3 browser, navigate to:
   ```
   https://<YOUR_IP>:5173
   ```

3. Accept the self-signed certificate warning

4. Click "Enter Garvis XR"

5. Grant microphone permission when prompted

### WebXR Requirements

- **HTTPS** — Required for microphone access
- **Permissions** — Microphone must be allowed
- **Quest Browser** — Built-in browser works best

## 🎨 Components

### ChatLog

HUD overlay displaying conversation history.

```tsx
import { ChatLog } from './components/visor/ChatLog'

// In XR scene
<ChatLog />
```

**Features:**
- Follows user's head position
- Displays user and assistant messages
- Shows listening/speaking status
- Auto-scrolls to latest message

### VideoWindow

3D floating video player panel for live streams.

```tsx
import { VideoWindow } from './components/video/VideoWindow'

// In XR scene - renders when ActiveVideo.url is set
<VideoWindow />
```

**Features:**
- HLS video playback via hls.js
- VideoTexture rendering on 3D plane (WebXR compatible)
- Draggable title bar for repositioning
- Resizable via corner handle (0.5x to 2x scale)
- Tap to unmute/play controls
- Follows camera with configurable offset
- Close button to dismiss

**Controls:**

| Interaction | Action |
|-------------|--------|
| Tap video (first time) | Unmute audio |
| Tap video (subsequent) | Toggle play/pause |
| Drag title bar | Move window in 3D space |
| Drag ⤡ corner | Resize window |
| Click ✕ | Close video |

**State Management:**

The video URL is managed via the `ActiveVideo` ECS trait:

```typescript
// Open a video
setActiveVideo('/mcp/proxy/playlist.m3u8?channel=926&cdn=0')

// Close video
closeVideo()

// Check state
const { url, isPlaying } = getActiveVideo()
```

## 🔌 ECS State (Koota)

State is managed using Koota's Entity Component System pattern.

### Traits

```typescript
// ecs/traits.ts
export const VoiceState = trait({
  listening: false,
  speaking: false,
  connected: false
})

export const Transcript = trait({
  messages: [] as Message[]
})

export const ActiveVideo = trait({
  url: null as string | null,
  isPlaying: false
})
```

### Actions

```typescript
// ecs/actions.ts
export function setListening(listening: boolean) {
  world.get(VoiceState).listening = listening
}

export function addMessage(role: 'user' | 'assistant', text: string) {
  world.get(Transcript).messages.push({ role, text })
}
```

### Using in Components

```typescript
import { useWorld, useTrait } from 'koota/react'
import { VoiceState } from './ecs/traits'

function StatusIndicator() {
  const voiceState = useTrait(VoiceState)
  
  return (
    <div>
      {voiceState.listening && <span>🎤 Listening...</span>}
      {voiceState.speaking && <span>🔊 Speaking...</span>}
    </div>
  )
}
```

## ⚙️ Configuration

### Vite Config

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

export default defineConfig({
  plugins: [react(), basicSsl()],
  
  server: {
    https: true,  // Required for WebXR + Microphone
    host: '0.0.0.0',  // Allow LAN access
    
    proxy: {
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      },
      '/api': {
        target: 'http://localhost:8000'
      }
    }
  }
})
```

### Audio Settings

In `garvis-client.ts`:

```typescript
// Microphone capture settings
const constraints = {
  audio: {
    channelCount: 1,
    sampleRate: 16000,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  }
}
```

## 🐛 Troubleshooting

### "getUserMedia not allowed"

- Ensure using HTTPS
- Accept certificate warning
- Grant microphone permission
- On Quest, check browser permissions in Settings

### "WebSocket connection failed"

- Verify server is running on port 8000
- Check Vite proxy configuration
- Ensure same network for Quest 3

### "XR session not supported"

- Use Quest Browser or Chrome
- Enable WebXR flags if needed
- Check device compatibility

### "Audio not playing"

- Click/tap to trigger user interaction first
- Check browser autoplay policies
- Verify server TTS is working

### "Video shows black screen"

- Tap the video to unmute (required for autoplay)
- Check browser console for HLS.js errors
- Verify the proxy is running (`/mcp/proxy/*` endpoints)
- Check network tab for 404s on video chunks

### "Video window not appearing"

- Check console for `📺` logs showing stream URL receipt
- Verify `ActiveVideo` trait is being set in ECS
- Ensure VideoWindow component is rendered in App.tsx

## 🎯 Performance Tips

1. **Reduce draw calls** — Merge geometries where possible
2. **Simple materials** — Use MeshBasicMaterial in XR
3. **Limit updates** — Use `useFrame` sparingly
4. **Pool objects** — Reuse Three.js objects

## 📦 Building

```bash
# Production build
npm run build

# Output in dist/
# Deploy dist/ to any static host
```

### Hosting Requirements

- HTTPS with valid certificate
- WebSocket proxy support
- Correct CORS headers

## 📜 License

MIT
