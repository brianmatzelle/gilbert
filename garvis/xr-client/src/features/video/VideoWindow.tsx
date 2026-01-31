/**
 * Video Window Component
 * 
 * Video player wrapped in a Window from the design system.
 */

import { useState, useEffect } from 'react'
import { world } from '../../ecs/world'
import { ActiveVideo, VisorConfig, DEFAULT_VISOR_CONFIG, type VisorConfigData } from '../../ecs/traits'
import { closeVideo } from '../../ecs/actions'
import { Window, opacity } from '../../design-system'
import { VideoContent } from './VideoContent'

function VideoPanel({ url, config }: { url: string; config: VisorConfigData }) {
  const videoWidth = 0.45
  const videoHeight = videoWidth * (9 / 16)

  return (
    <Window
      title="Stream"
      icon="📺"
      width={videoWidth + 0.02}
      height={videoHeight + 0.02}
      config={{
        distance: config.distance * 1.5,
        horizontalOffset: 0,
        verticalOffset: config.verticalOffset - 0.1,
        horizontalMode: config.horizontalMode,
      }}
      showClose={true}
      onClose={closeVideo}
      draggable={true}
      resizable={true}
      minScale={0.5}
      maxScale={2.0}
      bgOpacity={opacity.glass}
      storageKey="video"
    >
      <VideoContent url={url} width={videoWidth} />
    </Window>
  )
}

export function VideoWindow() {
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [config, setConfig] = useState<VisorConfigData>(DEFAULT_VISOR_CONFIG)

  useEffect(() => {
    const interval = setInterval(() => {
      try {
        const video = world.get(ActiveVideo)
        if (video && video.url !== videoUrl) {
          setVideoUrl(video.url)
        } else if (!video && videoUrl) {
          setVideoUrl(null)
        }
        const visorConfig = world.get(VisorConfig)
        if (visorConfig) {
          setConfig({ ...visorConfig })
        }
      } catch (err) {
        console.error('📺 Error polling ECS:', err)
      }
    }, 100)
    return () => clearInterval(interval)
  }, [videoUrl])

  if (!videoUrl) return null

  return <VideoPanel url={videoUrl} config={config} />
}

