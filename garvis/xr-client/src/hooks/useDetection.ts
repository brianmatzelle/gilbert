import { useRef, useState, useEffect, useCallback } from 'react'
import { useXR } from '@react-three/xr'

export interface BoundingBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface Detection {
  id: number
  class: string
  confidence: number
  bbox: BoundingBox
}

export interface DetectionState {
  isActive: boolean
  detections: Detection[]
  fps: number
  latency: number
  imageSize: { width: number; height: number } | null
  error: string | null
}

interface UseDetectionOptions {
  /** Target detection frames per second */
  targetFps?: number
  /** Minimum confidence threshold (0-1) */
  confidence?: number
  /** Maximum detections to return */
  maxDetections?: number
  /** Detection server URL (empty = use proxy) */
  serverUrl?: string
}

/**
 * Hook for running object detection on camera frames
 * 
 * Captures frames from the camera, sends to detection server,
 * and returns detected objects with bounding boxes.
 */
export function useDetection(
  captureFrame: () => string | null,
  imageSize: { width: number; height: number } | null,
  options: UseDetectionOptions = {}
) {
  const {
    targetFps = 5,
    confidence = 0.5,
    maxDetections = 15,
    serverUrl = ''
  } = options

  const session = useXR((state) => state.session)
  const isPresenting = !!session

  const [state, setState] = useState<DetectionState>({
    isActive: false,
    detections: [],
    fps: 0,
    latency: 0,
    imageSize: null,
    error: null,
  })

  // Refs for detection loop
  const isActiveRef = useRef(false)
  const isProcessingRef = useRef(false)
  const intervalRef = useRef<number | null>(null)
  const frameCountRef = useRef(0)
  const fpsIntervalRef = useRef<number | null>(null)

  const safeTargetFps = Number.isFinite(targetFps) ? Math.max(1, targetFps) : 5
  const frameInterval = 1000 / safeTargetFps

  // Detection function
  const detectFrame = useCallback(async () => {
    if (isProcessingRef.current) {
      return
    }

    const base64 = captureFrame()
    if (!base64) {
      return
    }

    isProcessingRef.current = true
    const startTime = performance.now()

    try {
      const detectUrl = serverUrl ? `${serverUrl}/detect` : '/detect'
      
      const response = await fetch(detectUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: base64,
          confidence,
          max_detections: maxDetections
        })
      })

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`)
      }

      const result = await response.json()
      const latency = Math.round(performance.now() - startTime)

      if (result.success) {
        frameCountRef.current++
        setState(prev => ({
          ...prev,
          detections: result.detections || [],
          latency,
          imageSize: imageSize,
          error: null
        }))
      } else {
        setState(prev => ({
          ...prev,
          error: result.error || 'Detection failed'
        }))
      }

    } catch (err) {
      // Don't spam errors - just log occasionally
      if (Math.random() < 0.1) {
        console.warn('Detection error:', err)
      }
      setState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : 'Detection failed'
      }))
    } finally {
      isProcessingRef.current = false
    }
  }, [captureFrame, serverUrl, confidence, maxDetections, imageSize])

  // Start/stop detection based on XR session
  useEffect(() => {
    console.log('👁️ Object detection effect:', { isPresenting, imageSize })
    
    if (!isPresenting || !imageSize) {
      // Stop detection
      isActiveRef.current = false
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      if (fpsIntervalRef.current) {
        clearInterval(fpsIntervalRef.current)
        fpsIntervalRef.current = null
      }
      setState(prev => ({
        ...prev,
        isActive: false,
        detections: [],
        fps: 0
      }))
      return
    }

    // Start detection loop
    console.log('👁️ Starting object detection loop...')
    isActiveRef.current = true
    setState(prev => ({ ...prev, isActive: true, error: null }))

    const intervalId = window.setInterval(() => {
      if (!isActiveRef.current) {
        clearInterval(intervalId)
        return
      }

      detectFrame()
    }, frameInterval)
    
    intervalRef.current = intervalId as unknown as number

    // FPS counter
    fpsIntervalRef.current = window.setInterval(() => {
      setState(prev => ({
        ...prev,
        fps: frameCountRef.current
      }))
      frameCountRef.current = 0
    }, 1000)

    return () => {
      isActiveRef.current = false
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
      }
      if (fpsIntervalRef.current) {
        clearInterval(fpsIntervalRef.current)
      }
    }
  }, [isPresenting, imageSize, frameInterval, detectFrame])

  return state
}
