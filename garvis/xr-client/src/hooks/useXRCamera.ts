import { useRef, useState, useEffect, useCallback } from 'react'
import { useXR } from '@react-three/xr'
import * as THREE from 'three'

export interface XRCameraState {
  /** Whether camera is available and streaming */
  isAvailable: boolean
  /** Whether we're currently receiving frames */
  isStreaming: boolean
  /** Width of the camera image */
  width: number
  /** Height of the camera image */
  height: number
  /** Frames captured per second */
  fps: number
  /** Error message if camera access failed */
  error: string | null
}

interface XRCameraResult {
  /** Current camera state */
  state: XRCameraState
  /** Three.js texture containing the camera feed */
  texture: THREE.VideoTexture | null
  /** Video element for frame capture */
  videoElement: HTMLVideoElement | null
  /** Canvas element for frame extraction */
  canvasElement: HTMLCanvasElement | null
  /** Capture current frame as base64 JPEG */
  captureFrame: (quality?: number) => string | null
}

/**
 * Hook to access device camera via getUserMedia for use in WebXR
 */
export function useXRCamera(): XRCameraResult {
  const session = useXR((state) => state.session)
  const isPresenting = !!session
  
  const [state, setState] = useState<XRCameraState>({
    isAvailable: false,
    isStreaming: false,
    width: 0,
    height: 0,
    fps: 0,
    error: null
  })
  
  // Store elements in state so changes trigger re-render
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null)
  const [canvasElement, setCanvasElement] = useState<HTMLCanvasElement | null>(null)
  const [texture, setTexture] = useState<THREE.VideoTexture | null>(null)
  
  // Keep refs for internal use
  const streamRef = useRef<MediaStream | null>(null)
  const frameCountRef = useRef(0)
  const fpsIntervalRef = useRef<number | null>(null)

  // Start camera when entering XR
  useEffect(() => {
    if (!isPresenting) {
      // Cleanup when exiting XR
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop())
        streamRef.current = null
      }
      if (texture) {
        texture.dispose()
      }
      if (videoElement && videoElement.parentNode) {
        videoElement.parentNode.removeChild(videoElement)
      }
      if (fpsIntervalRef.current) {
        clearInterval(fpsIntervalRef.current)
        fpsIntervalRef.current = null
      }
      
      setVideoElement(null)
      setCanvasElement(null)
      setTexture(null)
      setState(prev => ({
        ...prev,
        isAvailable: false,
        isStreaming: false,
        fps: 0
      }))
      return
    }

    const startCamera = async () => {
      try {
        console.log('📷 Requesting camera access...')
        
        // Create video element
        const video = document.createElement('video')
        video.playsInline = true
        video.muted = true
        video.autoplay = true
        // Keep it in DOM but hidden
        video.style.position = 'fixed'
        video.style.top = '0'
        video.style.left = '0'
        video.style.width = '1px'
        video.style.height = '1px'
        video.style.opacity = '0.01'
        video.style.pointerEvents = 'none'
        video.style.zIndex = '-1000'
        document.body.appendChild(video)

        // Create canvas for frame capture
        const canvas = document.createElement('canvas')

        // Request camera - prefer back/environment camera
        let stream: MediaStream
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: {
              facingMode: { ideal: 'environment' },
              width: { ideal: 640 },
              height: { ideal: 480 }
            },
            audio: false
          })
        } catch {
          console.warn('📷 Environment camera failed, trying default')
          stream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: false
          })
        }

        streamRef.current = stream
        video.srcObject = stream

        // Wait for video to be ready
        await new Promise<void>((resolve, reject) => {
          video.onloadedmetadata = () => {
            video.play()
              .then(() => resolve())
              .catch(reject)
          }
          video.onerror = () => reject(new Error('Video load failed'))
          // Timeout after 10s
          setTimeout(() => reject(new Error('Video timeout')), 10000)
        })

        const width = video.videoWidth
        const height = video.videoHeight

        console.log(`📷 Camera ready: ${width}x${height}`)

        // Set canvas size
        canvas.width = width
        canvas.height = height

        // Create Three.js VideoTexture
        const videoTexture = new THREE.VideoTexture(video)
        videoTexture.minFilter = THREE.LinearFilter
        videoTexture.magFilter = THREE.LinearFilter
        videoTexture.format = THREE.RGBAFormat
        videoTexture.generateMipmaps = false

        // Update state - this triggers re-render with new elements
        setVideoElement(video)
        setCanvasElement(canvas)
        setTexture(videoTexture)
        
        setState({
          isAvailable: true,
          isStreaming: true,
          width,
          height,
          fps: 0,
          error: null
        })

        // Start FPS counter
        fpsIntervalRef.current = window.setInterval(() => {
          setState(prev => ({
            ...prev,
            fps: frameCountRef.current
          }))
          frameCountRef.current = 0
        }, 1000)

      } catch (err) {
        console.error('📷 Camera error:', err)
        setState(prev => ({
          ...prev,
          isAvailable: false,
          isStreaming: false,
          error: err instanceof Error ? err.message : 'Camera access failed'
        }))
      }
    }

    startCamera()

    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(track => track.stop())
      }
      if (fpsIntervalRef.current) {
        clearInterval(fpsIntervalRef.current)
      }
    }
  }, [isPresenting]) // Note: texture, videoElement removed from deps intentionally

  // Capture current frame as base64 JPEG
  const captureFrame = useCallback((quality: number = 0.7): string | null => {
    if (!videoElement || !canvasElement) {
      return null
    }
    
    if (videoElement.readyState < 2) {
      return null
    }

    const ctx = canvasElement.getContext('2d')
    if (!ctx) return null

    // Draw video frame to canvas
    ctx.drawImage(videoElement, 0, 0, canvasElement.width, canvasElement.height)
    
    // Convert to base64 JPEG (strip data URL prefix)
    const dataUrl = canvasElement.toDataURL('image/jpeg', quality)
    const base64 = dataUrl.split(',')[1]
    
    // Track frame capture
    frameCountRef.current++
    
    return base64
  }, [videoElement, canvasElement])

  return {
    state,
    texture,
    videoElement,
    canvasElement,
    captureFrame
  }
}

