import { trait } from 'koota'

// A single chat message
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

// Chat history stored on the world
export const ChatHistory = trait(() => ({
  messages: [] as ChatMessage[]
}))

// Voice assistant state
export const VoiceState = trait({
  isListening: false,
  isSpeaking: false,
  isProcessing: false,
  isPaused: false, // User can pause the assistant
  shouldReset: false, // Signal to reset conversation
  isConnected: false, // WebSocket connection status
  error: null as string | null
})

// Visor configuration (customizable by user)
export type ChatHorizontalMode = 'visor' | 'yaw'

export interface VisorConfigData {
  distance: number // How far from face (0.2 - 0.8)
  horizontalOffset: number // Horizontal position (-0.2 - 0.3)
  verticalOffset: number // How far up/down (-0.15 - 0.1)
  horizontalMode: ChatHorizontalMode // 'visor' = camera-right HUD, 'yaw' = world-horizontal yaw-locked
  fontSize: number // Text size multiplier (0.5 - 2.0)
  maxWidth: number // Text wrap width (0.08 - 0.25)
}

export const DEFAULT_VISOR_CONFIG: VisorConfigData = {
  distance: 0.35,
  horizontalOffset: 0.04,
  verticalOffset: -0.03,
  horizontalMode: 'visor',
  fontSize: 1.0,
  maxWidth: 0.12
}

export const VisorConfig = trait({
  ...DEFAULT_VISOR_CONFIG
})

// UI state for settings panel
export const SettingsUIState = trait({
  isOpen: false
})

// Control bar UI state
export const ControlBarState = trait({
  isHovered: false
})

// Active video stream state
export const ActiveVideo = trait({
  url: null as string | null,
  isPlaying: false
})

