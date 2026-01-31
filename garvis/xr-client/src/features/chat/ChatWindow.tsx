/**
 * Chat Window Component
 * 
 * The chat log wrapped in a Window from the design system.
 * Includes mute and reset actions in the title bar.
 */

import { useState, useEffect } from 'react'
import { world } from '../../ecs/world'
import { VisorConfig, VoiceState, DEFAULT_VISOR_CONFIG, type VisorConfigData } from '../../ecs/traits'
import { togglePaused, resetConversation } from '../../ecs/actions'
import { Window, opacity, type WindowAction } from '../../design-system'
import { ChatContent } from './ChatContent'

export function ChatWindow() {
  const [config, setConfig] = useState<VisorConfigData>(DEFAULT_VISOR_CONFIG)
  const [isPaused, setIsPaused] = useState(false)

  useEffect(() => {
    const interval = setInterval(() => {
      const visorConfig = world.get(VisorConfig)
      if (visorConfig) setConfig({ ...visorConfig })
      
      const voiceState = world.get(VoiceState)
      if (voiceState) setIsPaused(voiceState.isPaused)
    }, 50)
    return () => clearInterval(interval)
  }, [])

  // Window dimensions based on config
  const windowWidth = config.maxWidth + 0.04
  const windowHeight = 0.22

  // Title bar actions
  const actions: WindowAction[] = [
    {
      key: 'mute',
      icon: isPaused ? '🔇' : '🎤',
      variant: isPaused ? 'error' : 'success',
      active: isPaused,
      onPress: togglePaused,
    },
    {
      key: 'reset',
      icon: '🗑️',
      variant: 'error',
      onPress: resetConversation,
    },
  ]

  return (
    <Window
      title="Chat"
      icon="💬"
      width={windowWidth}
      height={windowHeight}
      config={{
        distance: config.distance,
        horizontalOffset: config.horizontalOffset,
        verticalOffset: config.verticalOffset,
        horizontalMode: config.horizontalMode,
      }}
      showClose={false}
      actions={actions}
      draggable={true}
      resizable={true}
      minScale={0.5}
      maxScale={2.0}
      bgOpacity={opacity.glass}
      storageKey="chat"
    >
      <ChatContent config={config} />
    </Window>
  )
}
