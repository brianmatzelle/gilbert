import { useRef, useState, useEffect, useCallback } from 'react'
import { useXR } from '@react-three/xr'

export interface BoundingBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface FaceDetectionData {
  id: number
  confidence: number
  bbox: BoundingBox
  center?: { x: number; y: number }
  searchState: 'idle' | 'searching' | 'found' | 'not_found'
  personName?: string | null
}

export interface FaceDetectionState {
  isActive: boolean
  detections: FaceDetectionData[]
  fps: number
  latency: number
  imageSize: { width: number; height: number } | null
  error: string | null
  searchingCount: number
}

interface UseFaceDetectionOptions {
  /** Target detection frames per second */
  targetFps?: number
  /** Minimum confidence threshold (0-1) */
  confidence?: number
  /** Maximum face detections to return */
  maxDetections?: number
  /** Detection server URL (empty = use proxy) */
  serverUrl?: string
}

/**
 * Hook for face detection in XR
 * 
 * Detects faces in camera frames and returns bounding boxes.
 * Includes placeholder for future identity search functionality.
 */
export function useFaceDetection(
  captureFrame: () => string | null,
  imageSize: { width: number; height: number } | null,
  options: UseFaceDetectionOptions = {}
) {
  const {
    targetFps = 3,
    confidence = 0.5,
    maxDetections = 5,
    serverUrl = ''
  } = options

  const session = useXR((state) => state.session)
  const isPresenting = !!session

  const [state, setState] = useState<FaceDetectionState>({
    isActive: false,
    detections: [],
    fps: 0,
    latency: 0,
    imageSize: null,
    error: null,
    searchingCount: 0
  })

  // Refs for detection loop
  const isActiveRef = useRef(false)
  const isProcessingRef = useRef(false)
  const intervalRef = useRef<number | null>(null)
  const fpsIntervalRef = useRef<number | null>(null)
  const frameCountRef = useRef(0)
  
  // Track which faces are being "searched" (for future use)
  const searchingFacesRef = useRef<Set<number>>(new Set())

  const safeTargetFps = Number.isFinite(targetFps) ? Math.max(1, targetFps) : 3
  const frameInterval = 1000 / safeTargetFps

  /**
   * Start searching for a face's identity
   * Placeholder for future implementation - will call /identify endpoint
   */
  const startSearch = useCallback((faceId: number) => {
    // Mark face as searching
    searchingFacesRef.current.add(faceId)
    
    setState(prev => ({
      ...prev,
      searchingCount: searchingFacesRef.current.size,
      detections: prev.detections.map(d =>
        d.id === faceId ? { ...d, searchState: 'searching' as const } : d
      )
    }))
    
    // TODO: Future implementation - call /identify endpoint
    // For now, simulate a search that completes after 3 seconds
    setTimeout(() => {
      searchingFacesRef.current.delete(faceId)
      setState(prev => ({
        ...prev,
        searchingCount: searchingFacesRef.current.size,
        detections: prev.detections.map(d =>
          d.id === faceId ? { ...d, searchState: 'not_found' as const } : d
        )
      }))
    }, 3000)
    
    console.log(`🔍 Started search for face ${faceId}`)
  }, [])

  /**
   * Stop searching for a face
   */
  const stopSearch = useCallback((faceId: number) => {
    searchingFacesRef.current.delete(faceId)
    setState(prev => ({
      ...prev,
      searchingCount: searchingFacesRef.current.size,
      detections: prev.detections.map(d =>
        d.id === faceId ? { ...d, searchState: 'idle' as const } : d
      )
    }))
  }, [])

  // Face detection function
  const detectFaces = useCallback(async () => {
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
      const detectUrl = serverUrl ? `${serverUrl}/detect-faces` : '/detect-faces'
      
      const response = await fetch(detectUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image_base64: base64,
          confidence,
          max_detections: maxDetections,
          include_crops: false
        })
      })

      if (!response.ok) {
        throw new Error(`Server error: ${response.status}`)
      }

      const result = await response.json()
      const latency = Math.round(performance.now() - startTime)

      if (result.success) {
        frameCountRef.current++
        
        // Map server response to FaceDetectionData format
        // Preserve search state for faces that are already being searched
        const faceDetections: FaceDetectionData[] = (result.detections || []).map(
          (d: any, i: number) => {
            const faceId = d.id ?? i
            const isSearching = searchingFacesRef.current.has(faceId)
            
            return {
              id: faceId,
              confidence: d.confidence,
              bbox: d.bbox,
              center: d.center,
              searchState: isSearching ? 'searching' : 'idle',
              personName: null
            } as FaceDetectionData
          }
        )
        
        setState(prev => ({
          ...prev,
          detections: faceDetections,
          latency,
          imageSize: imageSize,
          error: null
        }))
        
      } else {
        setState(prev => ({
          ...prev,
          error: result.error || 'Face detection failed'
        }))
      }

    } catch (err) {
      if (Math.random() < 0.1) {
        console.warn('Face detection error:', err)
      }
      setState(prev => ({
        ...prev,
        error: err instanceof Error ? err.message : 'Face detection failed'
      }))
    } finally {
      isProcessingRef.current = false
    }
  }, [captureFrame, serverUrl, confidence, maxDetections, imageSize])

  // Start/stop detection based on XR session
  useEffect(() => {
    console.log('👤 Face detection effect:', { isPresenting, imageSize })
    
    if (!isPresenting || !imageSize) {
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

    console.log('👤 Starting face detection loop...')
    isActiveRef.current = true
    setState(prev => ({ ...prev, isActive: true, error: null }))

    // Detection loop
    intervalRef.current = window.setInterval(() => {
      if (!isActiveRef.current) {
        if (intervalRef.current) clearInterval(intervalRef.current)
        return
      }
      detectFaces()
    }, frameInterval)

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
  }, [isPresenting, imageSize, frameInterval, detectFaces])

  // Clear search state when session ends
  useEffect(() => {
    if (!isPresenting) {
      searchingFacesRef.current.clear()
    }
  }, [isPresenting])

  return {
    ...state,
    startSearch,
    stopSearch
  }
}

