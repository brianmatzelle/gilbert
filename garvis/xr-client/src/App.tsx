import { useEffect, useState, useMemo, useCallback, createContext, useContext } from 'react'
import { Canvas } from '@react-three/fiber'
import { XR, createXRStore, useXR } from '@react-three/xr'
import * as THREE from 'three'
import { initializeWorld } from './ecs/world'
import { useVoiceAssistant } from './voice/useVoiceAssistant'
import { ChatWindow, VideoWindow } from './features'
import { colors } from './design-system'
import { useXRCamera, type XRCameraState } from './hooks/useXRCamera'
import { useFaceDetection, type FaceDetectionData, type FaceDetectionState } from './hooks/useFaceDetection'
import { useDetection, type Detection, type DetectionState } from './hooks/useDetection'
import { XRCameraFeedDisplay } from './components'

// Create XR store
const xrStore = createXRStore()

// Context to share camera state and detections between components
interface CameraContextValue {
  state: XRCameraState
  texture: THREE.VideoTexture | null
  videoElement: HTMLVideoElement | null
  canvasElement: HTMLCanvasElement | null
  faceDetections: FaceDetectionData[]
  faceDetectionState: FaceDetectionState | null
  objectDetections: Detection[]
  objectDetectionState: DetectionState | null
  startSearch: (faceId: number) => void
}

const CameraContext = createContext<CameraContextValue | null>(null)

export function useCameraContext() {
  const ctx = useContext(CameraContext)
  if (!ctx) throw new Error('useCameraContext must be used within CameraProvider')
  return ctx
}

interface VisionSettings {
  faceFps: number
  confidence: number
  enabled: boolean
  showVideo: boolean
  objectDetection: boolean
}

const SettingsContext = createContext<{
  settings: VisionSettings
  setSettings: React.Dispatch<React.SetStateAction<VisionSettings>>
} | null>(null)

function useSettings() {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('useSettings must be used within SettingsContext.Provider')
  return ctx
}

/**
 * Camera provider - manages camera, detection, and shares state
 */
function CameraProvider({ children }: { children: React.ReactNode }) {
  const camera = useXRCamera()
  const { settings } = useSettings()
  
  // Create captureFrame for detection
  const captureFrame = useCallback((): string | null => {
    if (!camera.videoElement || !camera.canvasElement) {
      return null
    }
    
    if (camera.videoElement.readyState < 2) {
      return null
    }

    const ctx = camera.canvasElement.getContext('2d')
    if (!ctx) {
      return null
    }

    // Ensure canvas matches video size
    if (camera.canvasElement.width !== camera.videoElement.videoWidth) {
      camera.canvasElement.width = camera.videoElement.videoWidth
    }
    if (camera.canvasElement.height !== camera.videoElement.videoHeight) {
      camera.canvasElement.height = camera.videoElement.videoHeight
    }

    // Draw video frame to canvas
    ctx.drawImage(camera.videoElement, 0, 0)
    
    // Convert to base64 JPEG (strip data URL prefix)
    const dataUrl = camera.canvasElement.toDataURL('image/jpeg', 0.7)
    const base64 = dataUrl.split(',')[1]
    return base64
  }, [camera.videoElement, camera.canvasElement])
  
  // Memoize imageSize to prevent infinite effect loop in useFaceDetection
  const imageSize = useMemo(() => {
    if (!camera.state.isStreaming || !settings.enabled) return null
    return { width: camera.state.width, height: camera.state.height }
  }, [camera.state.isStreaming, camera.state.width, camera.state.height, settings.enabled])
  
  // Object detection image size (only enabled when objectDetection is on)
  const objectImageSize = useMemo(() => {
    if (!camera.state.isStreaming || !settings.enabled || !settings.objectDetection) return null
    return { width: camera.state.width, height: camera.state.height }
  }, [camera.state.isStreaming, camera.state.width, camera.state.height, settings.enabled, settings.objectDetection])
  
  // Face detection
  const faceDetection = useFaceDetection(captureFrame, imageSize, {
    targetFps: settings.faceFps,
    confidence: settings.confidence,
    maxDetections: 5
  })
  
  // Object detection (YOLO)
  const objectDetection = useDetection(captureFrame, objectImageSize, {
    targetFps: settings.faceFps,
    confidence: settings.confidence,
    maxDetections: 15
  })
  
  return (
    <CameraContext.Provider value={{
      state: camera.state,
      texture: camera.texture,
      videoElement: camera.videoElement,
      canvasElement: camera.canvasElement,
      faceDetections: faceDetection.detections,
      faceDetectionState: faceDetection,
      objectDetections: objectDetection.detections,
      objectDetectionState: objectDetection,
      startSearch: faceDetection.startSearch
    }}>
      {children}
    </CameraContext.Provider>
  )
}

/**
 * Camera feed with face and object detection overlays
 * Video is hidden by default - only bounding boxes are visible
 */
function CameraFeed() {
  const { state, texture, faceDetections, faceDetectionState, objectDetections, objectDetectionState } = useCameraContext()
  const { settings } = useSettings()

  return (
    <XRCameraFeedDisplay 
      state={state} 
      texture={texture} 
      detections={faceDetections}
      objectDetections={settings.objectDetection ? objectDetections : []}
      imageSize={faceDetectionState?.imageSize || objectDetectionState?.imageSize || null}
      showVideo={settings.showVideo}
    />
  )
}

function XRScene() {
  const session = useXR((state) => state.session)
  const isPresenting = !!session
  const { settings } = useSettings()

  // Initialize voice assistant when in XR
  useVoiceAssistant({ enabled: isPresenting })

  return (
    <>
      {/* Chat window - always visible in XR */}
      <ChatWindow />
      
      {/* Video window - renders when stream URL is active */}
      <VideoWindow />
      
      {/* Quest 3 Camera with face detection bounding boxes */}
      {settings.enabled && (
        <CameraProvider>
          <CameraFeed />
        </CameraProvider>
      )}
      
      {/* Ambient lighting */}
      <ambientLight intensity={0.5} />
    </>
  )
}

function App() {
  const [settings, setSettings] = useState<VisionSettings>(() => {
    const defaults: VisionSettings = { faceFps: 3, confidence: 0.5, enabled: true, showVideo: false, objectDetection: false }
    try {
      const raw = localStorage.getItem('garvisVisionSettings')
      if (!raw) return defaults
      const parsed = JSON.parse(raw) as Partial<VisionSettings>
      return {
        faceFps: typeof parsed.faceFps === 'number' ? parsed.faceFps : defaults.faceFps,
        confidence: typeof parsed.confidence === 'number' ? parsed.confidence : defaults.confidence,
        enabled: typeof parsed.enabled === 'boolean' ? parsed.enabled : defaults.enabled,
        showVideo: typeof parsed.showVideo === 'boolean' ? parsed.showVideo : defaults.showVideo,
        objectDetection: typeof parsed.objectDetection === 'boolean' ? parsed.objectDetection : defaults.objectDetection,
      }
    } catch {
      return defaults
    }
  })

  const [settingsOpen, setSettingsOpen] = useState(false)

  // Persist settings to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('garvisVisionSettings', JSON.stringify(settings))
    } catch {
      // ignore
    }
  }, [settings])

  // Initialize ECS world on mount
  useEffect(() => {
    initializeWorld()
  }, [])

  const handleEnterXR = async () => {
    try {
      await xrStore.enterAR()
    } catch (error) {
      console.error('Failed to enter XR:', error)
      // Try VR as fallback
      try {
        await xrStore.enterVR()
      } catch (vrError) {
        console.error('Failed to enter VR:', vrError)
      }
    }
  }

  return (
    <SettingsContext.Provider value={{ settings, setSettings }}>
      <div style={{ width: '100vw', height: '100vh', background: colors.bg.primary }}>
        {/* Header */}
        <div style={{
          position: 'absolute',
          top: '2rem',
          left: '50%',
          transform: 'translateX(-50%)',
          textAlign: 'center',
          color: '#888',
          fontSize: '0.9rem',
          zIndex: 10,
        }}>
          <h1 style={{
            fontSize: '1.5rem',
            color: '#00ffff',
            marginBottom: '0.5rem',
            fontWeight: 600,
            textShadow: '0 0 10px rgba(0, 255, 255, 0.5)'
          }}>
            GARVIS
          </h1>
          <p style={{ fontSize: '0.8rem', marginBottom: '0.5rem', color: '#667eea' }}>
            {settings.enabled 
              ? (settings.objectDetection ? '🎯 OBJECT DETECTION ACTIVE' : '👤 FACE DETECTION ACTIVE')
              : '🎙️ VOICE ASSISTANT'
            }
          </p>
        </div>

        {/* Vision Toggle */}
        <div style={{
          position: 'absolute',
          top: '2rem',
          right: '2rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.5rem',
          zIndex: 10
        }}>
          <button
            onClick={() => setSettings(s => ({ ...s, enabled: !s.enabled }))}
            style={{
              padding: '0.5rem 1rem',
              fontSize: '0.75rem',
              fontWeight: 600,
              background: settings.enabled ? '#00ffff' : '#1a1a1a',
              color: settings.enabled ? '#000' : '#ccc',
              border: '2px solid #333',
              borderRadius: '0.5rem',
              cursor: 'pointer',
              boxShadow: settings.enabled ? '0 0 10px rgba(0, 255, 255, 0.5)' : 'none',
            }}
          >
            👁️ VISION {settings.enabled ? 'ON' : 'OFF'}
          </button>
          {settings.enabled && (
            <>
              <button
                onClick={() => setSettings(s => ({ ...s, showVideo: !s.showVideo }))}
                style={{
                  padding: '0.5rem 1rem',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  background: settings.showVideo ? '#ff6b6b' : '#1a1a1a',
                  color: settings.showVideo ? '#000' : '#ccc',
                  border: '2px solid #333',
                  borderRadius: '0.5rem',
                  cursor: 'pointer',
                  boxShadow: settings.showVideo ? '0 0 10px rgba(255, 107, 107, 0.5)' : 'none',
                }}
              >
                📹 VIDEO {settings.showVideo ? 'ON' : 'OFF'}
              </button>
              <button
                onClick={() => setSettings(s => ({ ...s, objectDetection: !s.objectDetection }))}
                style={{
                  padding: '0.5rem 1rem',
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  background: settings.objectDetection ? '#39ff14' : '#1a1a1a',
                  color: settings.objectDetection ? '#000' : '#ccc',
                  border: '2px solid #333',
                  borderRadius: '0.5rem',
                  cursor: 'pointer',
                  boxShadow: settings.objectDetection ? '0 0 10px rgba(57, 255, 20, 0.5)' : 'none',
                }}
              >
                🎯 OBJECTS {settings.objectDetection ? 'ON' : 'OFF'}
              </button>
            </>
          )}
        </div>

        {/* Settings */}
        <div style={{ position: 'absolute', top: '2rem', left: '2rem', zIndex: 10 }}>
          <button
            onClick={() => setSettingsOpen(v => !v)}
            style={{
              padding: '0.5rem 0.75rem',
              fontSize: '0.75rem',
              fontWeight: 600,
              background: '#1a1a1a',
              color: '#00ffff',
              border: '2px solid #333',
              borderRadius: '0.5rem',
              cursor: 'pointer',
              boxShadow: '0 0 10px rgba(0, 255, 255, 0.15)',
            }}
          >
            ⚙ SETTINGS
          </button>

          {settingsOpen && (
            <div style={{
              marginTop: '0.5rem',
              padding: '0.75rem',
              width: '260px',
              background: 'rgba(0,0,0,0.75)',
              border: '2px solid #333',
              borderRadius: '0.5rem',
              color: '#ddd',
              fontSize: '0.75rem',
              backdropFilter: 'blur(6px)'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <span style={{ color: '#00ffff', fontWeight: 700 }}>VISION TUNING</span>
                <button
                  onClick={() => setSettingsOpen(false)}
                  style={{ background: 'transparent', border: 'none', color: '#aaa', cursor: 'pointer' }}
                  aria-label="Close settings"
                >
                  ✕
                </button>
              </div>

              <label style={{ display: 'block', marginTop: '0.5rem' }}>
                Face FPS: <span style={{ color: '#00ffff', fontWeight: 700 }}>{settings.faceFps}</span>
              </label>
              <input
                type="range"
                min={1}
                max={10}
                value={settings.faceFps}
                onChange={(e) => setSettings(s => ({ ...s, faceFps: Number(e.target.value) }))}
                style={{ width: '100%' }}
              />

              <label style={{ display: 'block', marginTop: '0.5rem' }}>
                Confidence: <span style={{ color: '#00ffff', fontWeight: 700 }}>{settings.confidence.toFixed(2)}</span>
              </label>
              <input
                type="range"
                min={0.1}
                max={0.9}
                step={0.05}
                value={settings.confidence}
                onChange={(e) => setSettings(s => ({ ...s, confidence: Number(e.target.value) }))}
                style={{ width: '100%' }}
              />
            </div>
          )}
        </div>

        {/* Enter XR button */}
        <button
          onClick={handleEnterXR}
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            padding: '20px 40px',
            fontSize: '24px',
            fontWeight: 'bold',
            background: `linear-gradient(135deg, ${colors.accent.primary} 0%, #764ba2 100%)`,
            color: colors.text.primary,
            border: 'none',
            borderRadius: '12px',
            cursor: 'pointer',
            boxShadow: `0 4px 20px ${colors.accent.primary}66`,
            zIndex: 1000,
          }}
        >
          Enter Garvis XR
        </button>

        <Canvas>
          <XR store={xrStore}>
            <XRScene />
          </XR>
        </Canvas>
      </div>
    </SettingsContext.Provider>
  )
}

export default App
