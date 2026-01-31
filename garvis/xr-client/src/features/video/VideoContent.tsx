/**
 * Video Content Component
 * 
 * The inner content of the video window - HLS video player with controls.
 */

import { useRef, useState, useEffect, useCallback } from 'react'
import { Text } from '@react-three/drei'
import * as THREE from 'three'
import { colors, typography, opacity, zLayers } from '../../design-system'

interface VideoContentProps {
  url: string
  width?: number
  height?: number
}

export function VideoContent({ url, width = 0.45, height }: VideoContentProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const materialRef = useRef<THREE.MeshBasicMaterial>(null)
  const textureRef = useRef<THREE.VideoTexture | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isMuted, setIsMuted] = useState(true)
  const hlsRef = useRef<any>(null)

  // Video dimensions (16:9 aspect ratio)
  const videoWidth = width
  const videoHeight = height ?? videoWidth * (9 / 16)

  // Initialize video and texture
  useEffect(() => {
    console.log('📺 VideoContent mounting with URL:', url)

    const video = document.createElement('video')
    video.crossOrigin = 'anonymous'
    video.muted = true
    video.playsInline = true
    video.autoplay = true
    video.style.display = 'none'
    document.body.appendChild(video)
    videoRef.current = video

    video.onplay = () => {
      console.log('📺 Video playing')
      setIsPlaying(true)
    }
    video.onpause = () => {
      console.log('📺 Video paused')
      setIsPlaying(false)
    }

    const videoTexture = new THREE.VideoTexture(video)
    videoTexture.minFilter = THREE.LinearFilter
    videoTexture.magFilter = THREE.LinearFilter
    videoTexture.format = THREE.RGBAFormat
    videoTexture.colorSpace = THREE.SRGBColorSpace
    videoTexture.generateMipmaps = false
    textureRef.current = videoTexture

    if (materialRef.current) {
      materialRef.current.map = videoTexture
      materialRef.current.needsUpdate = true
    }

    const loadHls = async () => {
      try {
        const HlsModule = await import('hls.js')
        const Hls = HlsModule.default

        if (Hls.isSupported()) {
          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: false,
            backBufferLength: 30,
            maxBufferLength: 30,
            fragLoadingTimeOut: 20000,
            manifestLoadingTimeOut: 20000,
            levelLoadingTimeOut: 20000,
            maxBufferSize: 30 * 1000 * 1000,
            liveSyncDurationCount: 3,
            liveMaxLatencyDurationCount: 10,
            liveDurationInfinity: true,
            autoStartLoad: true,
            startPosition: -1,
            debug: false,
          })

          hlsRef.current = hls
          hls.loadSource(url)
          hls.attachMedia(video)

          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            setIsLoading(false)
            video.play().then(() => setIsPlaying(true)).catch(() => setError('Tap to play'))
          })

          hls.on(Hls.Events.FRAG_LOADED, () => {
            if (video.readyState >= 2 && video.paused) {
              video.play().catch(() => {})
            }
          })

          hls.on(Hls.Events.ERROR, (_, data) => {
            if (data.fatal) {
              if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
                setError('Network error')
                hls.startLoad()
              } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
                hls.recoverMediaError()
              } else {
                setError('Stream error')
                setIsLoading(false)
              }
            }
          })
        } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
          video.src = url
          video.addEventListener('loadedmetadata', () => {
            setIsLoading(false)
            video.play().catch(() => setError('Tap to play'))
          }, { once: true })
        } else {
          setError('HLS not supported')
          setIsLoading(false)
        }
      } catch (err) {
        setError('Failed to load')
        setIsLoading(false)
      }
    }

    loadHls()

    return () => {
      if (hlsRef.current) { hlsRef.current.destroy(); hlsRef.current = null }
      if (videoRef.current) { videoRef.current.pause(); videoRef.current.src = ''; videoRef.current.remove(); videoRef.current = null }
      if (textureRef.current) { textureRef.current.dispose(); textureRef.current = null }
    }
  }, [url])

  // Update texture every frame
  useEffect(() => {
    let animationId: number

    const updateTexture = () => {
      const video = videoRef.current
      const texture = textureRef.current

      if (texture && video && video.readyState >= 1) {
        texture.needsUpdate = true
      }

      if (materialRef.current && textureRef.current && materialRef.current.map !== textureRef.current) {
        materialRef.current.map = textureRef.current
        materialRef.current.needsUpdate = true
      }

      animationId = requestAnimationFrame(updateTexture)
    }

    updateTexture()
    return () => cancelAnimationFrame(animationId)
  }, [])

  const handleTap = useCallback(() => {
    const video = videoRef.current
    if (video) {
      if (video.muted) {
        video.muted = false
        setIsMuted(false)
        if (video.paused) video.play().catch(console.error)
        return
      }
      if (video.paused) {
        video.play().then(() => { setError(null); setIsPlaying(true) }).catch(console.error)
      } else {
        video.pause()
      }
    }
  }, [])

  return (
    <group>
      {/* Video plane */}
      <mesh position={[0, 0, zLayers.overlay]} onPointerDown={(e) => { e.stopPropagation(); handleTap() }}>
        <planeGeometry args={[videoWidth, videoHeight]} />
        <meshBasicMaterial ref={materialRef} toneMapped={false} side={THREE.FrontSide} />
      </mesh>

      {/* Loading overlay */}
      {isLoading && (
        <>
          <mesh position={[0, 0, zLayers.controls]}>
            <planeGeometry args={[videoWidth, videoHeight]} />
            <meshBasicMaterial color={colors.bg.overlay} transparent opacity={opacity.strong} />
          </mesh>
          <Text
            position={[0, 0, zLayers.tooltip]}
            fontSize={typography.fontSize['2xl']}
            color={colors.accent.secondary}
            anchorX="center"
            anchorY="middle"
          >
            Loading...
          </Text>
        </>
      )}

      {/* Muted indicator */}
      {!isLoading && isMuted && (
        <Text
          position={[0, 0, zLayers.tooltip]}
          fontSize={typography.fontSize['3xl'] * 1.5}
          color={colors.text.primary}
          anchorX="center"
          anchorY="middle"
        >
          🔇 Tap for sound
        </Text>
      )}

      {/* Paused indicator */}
      {!isLoading && !isPlaying && !isMuted && (
        <Text
          position={[0, 0, zLayers.tooltip]}
          fontSize={typography.fontSize['3xl'] * 2}
          color={colors.text.primary}
          anchorX="center"
          anchorY="middle"
        >
          ▶
        </Text>
      )}

      {/* Error message */}
      {error && (
        <Text
          position={[0, -videoHeight / 2 - 0.02, zLayers.controls]}
          fontSize={typography.fontSize.lg}
          color={colors.warning.base}
          anchorX="center"
          anchorY="middle"
        >
          {error}
        </Text>
      )}
    </group>
  )
}

