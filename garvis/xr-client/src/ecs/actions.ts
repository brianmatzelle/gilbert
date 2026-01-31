import { world, saveConfig } from './world'
import {
  ChatHistory,
  VoiceState,
  VisorConfig,
  SettingsUIState,
  ControlBarState,
  ActiveVideo,
  DEFAULT_VISOR_CONFIG,
  type ChatMessage,
  type VisorConfigData
} from './traits'

export function addMessage(role: ChatMessage['role'], content: string) {
  const history = world.get(ChatHistory)
  if (!history) return

  const newMessage: ChatMessage = {
    role,
    content,
    timestamp: Date.now()
  }

  world.set(ChatHistory, {
    messages: [...history.messages, newMessage]
  })
}

export function updateMessage(role: ChatMessage['role'], content: string, timestamp: number) {
  const history = world.get(ChatHistory)
  if (!history) return

  // Find and update the message with matching timestamp, or add if not found
  const existingIndex = history.messages.findIndex(m => m.timestamp === timestamp)
  
  if (existingIndex >= 0) {
    const newMessages = [...history.messages]
    newMessages[existingIndex] = { role, content, timestamp }
    world.set(ChatHistory, { messages: newMessages })
  } else {
    world.set(ChatHistory, {
      messages: [...history.messages, { role, content, timestamp }]
    })
  }
}

export function clearMessages() {
  world.set(ChatHistory, { messages: [] })
}

// Reset conversation - clears messages AND signals the voice assistant to reconnect
export function resetConversation() {
  world.set(ChatHistory, { messages: [] })

  const state = world.get(VoiceState)
  if (state) {
    world.set(VoiceState, { ...state, shouldReset: true })
  }
}

export function consumeResetRequest(): boolean {
  const state = world.get(VoiceState)
  if (state?.shouldReset) {
    world.set(VoiceState, { ...state, shouldReset: false })
    return true
  }
  return false
}

export function setListening(listening: boolean) {
  const state = world.get(VoiceState)
  if (state) {
    world.set(VoiceState, { ...state, isListening: listening })
  }
}

export function setSpeaking(speaking: boolean) {
  const state = world.get(VoiceState)
  if (state) {
    world.set(VoiceState, { ...state, isSpeaking: speaking })
  }
}

export function setProcessing(processing: boolean) {
  const state = world.get(VoiceState)
  if (state) {
    world.set(VoiceState, { ...state, isProcessing: processing })
  }
}

export function setConnected(connected: boolean) {
  const state = world.get(VoiceState)
  if (state) {
    world.set(VoiceState, { ...state, isConnected: connected })
  }
}

export function setError(error: string | null) {
  const state = world.get(VoiceState)
  if (state) {
    world.set(VoiceState, { ...state, error })
  }
}

export function togglePaused() {
  const state = world.get(VoiceState)
  if (state) {
    world.set(VoiceState, { ...state, isPaused: !state.isPaused })
  }
}

export function isPaused(): boolean {
  const state = world.get(VoiceState)
  return state?.isPaused ?? false
}

export function updateVisorConfig(updates: Partial<VisorConfigData>) {
  const current = world.get(VisorConfig)
  if (current) {
    const newConfig = { ...current, ...updates }
    world.set(VisorConfig, newConfig)
    saveConfig(newConfig)
  }
}

export function resetVisorConfig() {
  world.set(VisorConfig, { ...DEFAULT_VISOR_CONFIG })
  saveConfig(DEFAULT_VISOR_CONFIG)
}

export function toggleSettings() {
  const state = world.get(SettingsUIState)
  if (state) {
    world.set(SettingsUIState, { isOpen: !state.isOpen })
  }
}

export function setSettingsOpen(isOpen: boolean) {
  world.set(SettingsUIState, { isOpen })
}

export function setControlBarHovered(isHovered: boolean) {
  world.set(ControlBarState, { isHovered })
}

// Video actions
export function setActiveVideo(url: string | null) {
  try {
    console.log('📺 setActiveVideo called with:', url)
    world.set(ActiveVideo, { url, isPlaying: url !== null })
  } catch (err) {
    console.error('📺 Error in setActiveVideo:', err)
  }
}

export function closeVideo() {
  try {
    console.log('📺 closeVideo called')
    world.set(ActiveVideo, { url: null, isPlaying: false })
  } catch (err) {
    console.error('📺 Error in closeVideo:', err)
  }
}

export function getActiveVideo() {
  try {
    return world.get(ActiveVideo)
  } catch (err) {
    console.error('📺 Error in getActiveVideo:', err)
    return null
  }
}
